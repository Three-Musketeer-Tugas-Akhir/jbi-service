"""
User Service.

Provides user-related business logic including password verification.
"""

import bcrypt
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.auth import User
from app.repositories.user_repository import UserRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.utils.password import generate_temporary_password, validate_password_strength


class UserService:
    """Service for user operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
        self.repository = UserRepository(session)
    
    async def authenticate(
        self, 
        email: str, 
        password: str
    ) -> Tuple[bool, Optional[User]]:
        """
        Authenticate user with email and password.
        
        Args:
            email: User email
            password: Plain text password
            
        Returns:
            Tuple of (success: bool, user: User or None)
            
        Note:
            Returns (False, None) for both non-existent user and wrong password
            to prevent user enumeration attacks.
        """
        # Validate inputs
        if not email or not password:
            return False, None
        
        # Enforce max password length to prevent DoS
        if len(password) > 1024:
            return False, None
        
        # Find user by email
        user = await self.repository.get_by_email(email)
        
        # If user not found, still perform dummy bcrypt to prevent timing attacks
        if user is None:
            # Dummy bcrypt check to prevent timing attacks
            bcrypt.checkpw(
                password.encode('utf-8'),
                b'$2b$12$' + b'0' * 53  # Dummy hash
            )
            return False, None
        
        # Check if user is active (still do bcrypt check to prevent timing attacks)
        password_bytes = password.encode('utf-8')
        stored_hash = user.password_hash.encode('utf-8')
        
        if not user.is_active:
            # Still perform bcrypt check to prevent timing attacks
            bcrypt.checkpw(password_bytes, stored_hash)
            return False, None
        
        # Verify password
        try:
            if bcrypt.checkpw(password_bytes, stored_hash):
                return True, user
            
            return False, None
        except Exception:
            # Handle malformed hashes or other bcrypt errors
            return False, None
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email address.
        
        Args:
            email: User email
            
        Returns:
            User instance or None if not found
        """
        if not email:
            return None
        
        return await self.repository.get_by_email(email)
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt.
        
        Args:
            password: Plain text password
            
        Returns:
            Bcrypt hash string
        """
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    
    def _validate_email(self, email: str) -> Optional[str]:
        """
        Validate email format.
        
        Args:
            email: Email to validate
            
        Returns:
            Error message if invalid, None if valid
        """
        if not email:
            return "Email is required."
        
        if len(email) > 255:
            return "Email must not exceed 255 characters."
        
        # Basic email format check
        if '@' not in email or '.' not in email.split('@')[-1]:
            return "Invalid email format."
        
        return None
    
    async def update_profile(
        self, 
        user_id: UUID, 
        email: Optional[str] = None
    ) -> dict:
        """
        Update user profile.
        
        Args:
            user_id: User UUID
            email: New email address (optional)
            
        Returns:
            Dict with success status, user, and message
        """
        try:
            # Get user
            user = await self.repository.get_by_id(user_id)
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            # Update email if provided
            if email is not None:
                # Validate email
                error = self._validate_email(email)
                if error:
                    return {
                        "success": False,
                        "message": error
                    }
                
                email = email.lower().strip()
                
                # Check if email is unchanged
                if email == user.email.lower():
                    return {
                        "success": True,
                        "user": user,
                        "message": "No changes to apply."
                    }
                
                # Check if email is already in use
                email_exists = await self.repository.email_exists(
                    email, 
                    exclude_user_id=user_id
                )
                if email_exists:
                    return {
                        "success": False,
                        "message": "This email address is already in use."
                    }
                
                # Update email
                await self.repository.update_email(user_id, email)
            
            await self.session.commit()
            
            # Refresh user data
            await self.session.refresh(user)
            
            return {
                "success": True,
                "user": user,
                "message": "Profile updated successfully."
            }
            
        except Exception as e:
            await self.session.rollback()
            logger = __import__('logging').getLogger(__name__)
            logger.exception("Error updating profile")
            return {
                "success": False,
                "message": "An error occurred while updating your profile."
            }
    
    async def change_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str
    ) -> dict:
        """
        Change user password.
        
        Args:
            user_id: User UUID
            current_password: Current password
            new_password: New password
            
        Returns:
            Dict with success status and message
        """
        try:
            # Get user
            user = await self.repository.get_by_id(user_id)
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            # Validate current password
            password_bytes = current_password.encode('utf-8')
            stored_hash = user.password_hash.encode('utf-8')
            
            if not bcrypt.checkpw(password_bytes, stored_hash):
                return {
                    "success": False,
                    "message": "Current password is incorrect."
                }
            
            # Validate new password
            error = self._validate_new_password(new_password)
            if error:
                return {
                    "success": False,
                    "message": error
                }
            
            # Hash and update new password
            new_password_hash = self.hash_password(new_password)
            await self.repository.update_password(user_id, new_password_hash)
            
            await self.session.commit()
            
            logger = __import__('logging').getLogger(__name__)
            logger.info(f"Password changed successfully for user: {user.email}")
            
            return {
                "success": True,
                "message": "Password changed successfully."
            }
            
        except Exception as e:
            await self.session.rollback()
            logger = __import__('logging').getLogger(__name__)
            logger.exception("Error changing password")
            return {
                "success": False,
                "message": "An error occurred while changing your password."
            }
    
    def _validate_new_password(self, password: str) -> Optional[str]:
        """
        Validate new password strength.
        
        Args:
            password: Password to validate
            
        Returns:
            Error message if invalid, None if valid
        """
        if len(password) < 8:
            return "Password must be at least 8 characters long."
        
        if len(password) > 128:
            return "Password must not exceed 128 characters."
        
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password)
        
        if not (has_upper and has_lower and has_digit):
            return "Password must contain at least one uppercase letter, one lowercase letter, and one digit."
        
        if not has_special:
            return "Password must contain at least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)."
        
        # Check for common patterns
        common_patterns = ['password', '123456', 'qwerty', 'abc123']
        password_lower = password.lower()
        for pattern in common_patterns:
            if pattern in password_lower:
                return "Password is too common. Please choose a stronger password."
        
        return None
    
    # Admin methods
    
    ALLOWED_ROLES = {"admin", "annotator", "curator"}
    
    def _validate_role(self, role: str) -> Optional[str]:
        """
        Validate role value.
        
        Args:
            role: Role to validate
            
        Returns:
            Error message if invalid, None if valid
        """
        if not role:
            return "Role is required."
        
        if role not in self.ALLOWED_ROLES:
            return f"Invalid role. Must be one of: {', '.join(sorted(self.ALLOWED_ROLES))}"
        
        return None
    
    async def list_users(
        self,
        limit: int = 20,
        offset: int = 0,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
    ) -> dict:
        """
        List users with filtering and pagination (admin only).
        
        Args:
            limit: Maximum number of users to return
            offset: Number of users to skip
            role: Filter by role
            is_active: Filter by active status
            search: Search in email
            
        Returns:
            Dict with users list, total count, and pagination info
        """
        try:
            # Validate limit and offset
            if limit < 1:
                limit = 1
            if limit > 100:
                limit = 100
            if offset < 0:
                offset = 0
            
            # Validate role filter
            if role and role not in self.ALLOWED_ROLES:
                return {
                    "success": False,
                    "message": f"Invalid role filter. Must be one of: {', '.join(sorted(self.ALLOWED_ROLES))}"
                }
            
            users, total = await self.repository.list_users(
                limit=limit,
                offset=offset,
                role=role,
                is_active=is_active,
                search=search
            )
            
            return {
                "success": True,
                "users": users,
                "total": total,
                "limit": limit,
                "offset": offset
            }
            
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.exception("Error listing users")
            return {
                "success": False,
                "message": "An error occurred while listing users."
            }
    
    async def create_user(
        self,
        email: str,
        password: Optional[str] = None,
        roles: Optional[list] = None,
        is_active: bool = True,
        email_verified: bool = False
    ) -> dict:
        """
        Create a new user (admin only).
        
        If password is not provided, a secure temporary password will be
        auto-generated and returned in the response.
        
        Args:
            email: User email
            password: Plain text password (optional, auto-generated if not provided)
            roles: List of role names (default: ["annotator"])
            is_active: Whether user is active
            email_verified: Whether email is pre-verified
            
        Returns:
            Dict with success status, user, message, and temporary_password if generated
        """
        try:
            # Validate email
            error = self._validate_email(email)
            if error:
                return {
                    "success": False,
                    "message": error
                }
            
            email = email.lower().strip()
            
            # Generate or validate password
            generated_password = None
            if password is None:
                # Auto-generate temporary password
                generated_password = generate_temporary_password()
                password = generated_password
            else:
                # Validate provided password
                error = self._validate_new_password(password)
                if error:
                    return {
                        "success": False,
                        "message": error
                    }
            
            # Default roles
            if roles is None:
                roles = ["annotator"]
            
            # Validate roles
            for role in roles:
                error = self._validate_role(role)
                if error:
                    return {
                        "success": False,
                        "message": error
                    }
            
            # Check if email exists
            if await self.repository.email_exists(email):
                return {
                    "success": False,
                    "message": "A user with this email address already exists."
                }
            
            # Hash password
            password_hash = self.hash_password(password)
            
            # Create user with roles
            user = await self.repository.create_user(
                email=email,
                password_hash=password_hash,
                roles=roles,
                is_active=is_active,
                email_verified=email_verified
            )
            
            await self.session.commit()
            
            logger = __import__('logging').getLogger(__name__)
            logger.info(f"User created by admin: {user.email} (roles: {', '.join(roles)})")
            
            result = {
                "success": True,
                "user": user,
                "message": "User created successfully."
            }
            
            # Include generated password in response if auto-generated
            if generated_password:
                result["temporary_password"] = generated_password
            
            return result
            
        except Exception as e:
            await self.session.rollback()
            logger = __import__('logging').getLogger(__name__)
            logger.exception("Error creating user")
            return {
                "success": False,
                "message": "An error occurred while creating the user."
            }
    
    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """
        Get user by ID (admin only).
        
        Args:
            user_id: User UUID
            
        Returns:
            User instance or None
        """
        return await self.repository.get_by_id(user_id)
    
    async def admin_update_user(
        self,
        user_id: UUID,
        email: Optional[str] = None,
        roles: Optional[list] = None,
        is_active: Optional[bool] = None,
        email_verified: Optional[bool] = None
    ) -> dict:
        """
        Update user as admin.
        
        Args:
            user_id: User UUID to update
            email: New email (optional)
            roles: New roles list (optional)
            is_active: New active status (optional)
            email_verified: Set email verification (optional)
            
        Returns:
            Dict with success status, user, message, and previous_roles (if roles changed)
        """
        try:
            # Get user with roles
            user = await self.repository.get_by_id(user_id)
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            # Store previous values for response and audit
            current_roles = [r.name for r in user.roles] if user.roles else []
            previous_roles = current_roles.copy() if roles is not None else None
            
            # Validate email if provided
            if email is not None:
                error = self._validate_email(email)
                if error:
                    return {
                        "success": False,
                        "message": error
                    }
                
                email = email.lower().strip()
                
                # Check if email is already in use by another user
                if email != user.email.lower():
                    email_exists = await self.repository.email_exists(
                        email,
                        exclude_user_id=user_id
                    )
                    if email_exists:
                        return {
                            "success": False,
                            "message": "This email address is already in use by another user."
                        }
            
            # Validate roles if provided
            if roles is not None:
                for role in roles:
                    error = self._validate_role(role)
                    if error:
                        return {
                            "success": False,
                            "message": error
                        }
                
                # Check if roles are actually changing (same roles check)
                if set(roles) == set(current_roles):
                    return {
                        "success": False,
                        "message": f"User already has roles: {', '.join(roles)}."
                    }
            
            # Prevent deactivating the last admin
            if is_active is False:
                # Check if user has admin role
                is_admin = any(r.name == "admin" for r in user.roles)
                if is_admin:
                    # Count active admins
                    result = await self.repository.list_users(
                        limit=100,
                        role="admin",
                        is_active=True
                    )
                    active_admins = result[0]
                    
                    if len(active_admins) <= 1:
                        return {
                            "success": False,
                            "message": "Cannot deactivate the last active admin user."
                        }
            
            # Update user
            updated = await self.repository.update_user(
                user_id=user_id,
                email=email,
                roles=roles,
                is_active=is_active,
                email_verified=email_verified
            )
            
            if not updated:
                return {
                    "success": False,
                    "message": "Failed to update user."
                }
            
            await self.session.commit()
            
            # Refresh user data
            await self.session.refresh(user)
            
            logger = __import__('logging').getLogger(__name__)
            logger.info(f"User updated by admin: {user.email}")
            
            # Build response
            result = {
                "success": True,
                "user": user,
                "message": "User updated successfully."
            }
            
            # Include previous_roles in response if roles were changed
            if previous_roles is not None:
                result["previous_roles"] = previous_roles
            
            return result
            
        except Exception as e:
            await self.session.rollback()
            logger = __import__('logging').getLogger(__name__)
            logger.exception("Error updating user")
            return {
                "success": False,
                "message": "An error occurred while updating the user."
            }
    
    async def deactivate_user(self, user_id: UUID) -> dict:
        """
        Deactivate a user (admin only).
        
        Also revokes all active refresh tokens for the user to prevent
        continued access after deactivation.
        
        Args:
            user_id: User UUID to deactivate
            
        Returns:
            Dict with success status, message, and tokens_revoked count
        """
        try:
            # First deactivate the user
            result = await self.admin_update_user(user_id, is_active=False)
            
            if not result["success"]:
                return result
            
            # Revoke all refresh tokens for the user
            token_repo = RefreshTokenRepository(self.session)
            tokens_revoked = await token_repo.revoke_all_for_user(user_id)
            await self.session.commit()
            
            logger = __import__('logging').getLogger(__name__)
            logger.info(
                f"User deactivated and {tokens_revoked} tokens revoked: {result['user'].email}"
            )
            
            return {
                "success": True,
                "user": result["user"],
                "message": "User deactivated successfully.",
                "tokens_revoked": tokens_revoked
            }
            
        except Exception as e:
            await self.session.rollback()
            logger = __import__('logging').getLogger(__name__)
            logger.exception("Error deactivating user")
            return {
                "success": False,
                "message": "An error occurred while deactivating the user."
            }
    
    async def update_role(
        self,
        admin_id: UUID,
        target_user_id: UUID,
        new_role: str,
        ip_address: Optional[str] = None
    ) -> dict:
        """
        Update a user's role (admin only).
        
        Dedicated method for role updates with audit logging.
        Replaces all existing roles with the single new role.
        
        Args:
            admin_id: ID of admin making the change
            target_user_id: ID of user to update
            new_role: New role value (admin, annotator, curator)
            ip_address: Request IP address for audit logging
            
        Returns:
            Dict with success status, user, previous_role, and message
            
        Raises:
            ValueError: If validation fails (same role, self-modification, etc.)
        """
        from app.services.audit_service import AuditService
        
        try:
            # Validate role
            allowed_roles = {"admin", "annotator", "curator"}
            if new_role not in allowed_roles:
                return {
                    "success": False,
                    "message": f"Invalid role. Must be one of: {', '.join(sorted(allowed_roles))}"
                }
            
            # Get target user
            user = await self.repository.get_by_id(target_user_id)
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            # Check for self-modification
            if str(admin_id) == str(target_user_id):
                return {
                    "success": False,
                    "message": "Cannot modify your own role."
                }
            
            # Check if role is actually changing (compare primary role)
            current_roles = [r.name for r in user.roles] if user.roles else []
            old_role = current_roles[0] if current_roles else None
            if len(current_roles) == 1 and old_role == new_role:
                return {
                    "success": False,
                    "message": f"User already has role '{new_role}'."
                }
            
            # Update role (replaces all roles with single new role)
            updated = await self.repository.update_user(
                user_id=target_user_id,
                roles=[new_role]
            )
            
            if not updated:
                return {
                    "success": False,
                    "message": "Failed to update user role."
                }
            
            await self.session.commit()
            await self.session.refresh(user)
            
            # Log audit event
            audit_service = AuditService(self.session)
            await audit_service.log_user_roles_changed(
                actor_id=admin_id,
                target_user_id=target_user_id,
                old_roles=current_roles,
                new_roles=[new_role],
                ip_address=ip_address
            )
            await self.session.commit()
            
            logger = __import__('logging').getLogger(__name__)
            logger.info(f"User role changed by admin: {user.email} from {old_role} to {new_role}")
            
            return {
                "success": True,
                "user": user,
                "previous_role": old_role,
                "message": "User role updated successfully."
            }
            
        except Exception as e:
            await self.session.rollback()
            logger = __import__('logging').getLogger(__name__)
            logger.exception("Error updating user role")
            return {
                "success": False,
                "message": "An error occurred while updating the user role."
            }
    
    async def reactivate_user(self, user_id: UUID) -> dict:
        """
        Reactivate a deactivated user (admin only).
        
        Args:
            user_id: User UUID to reactivate
            
        Returns:
            Dict with success status, user, and message
        """
        try:
            # Get user
            user = await self.repository.get_by_id(user_id)
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            # Check if user is already active
            if user.is_active:
                return {
                    "success": False,
                    "message": "User is already active."
                }
            
            # Reactivate the user
            updated = await self.repository.update_user(
                user_id=user_id,
                is_active=True
            )
            
            if not updated:
                return {
                    "success": False,
                    "message": "Failed to reactivate user."
                }
            
            await self.session.commit()
            
            # Refresh user data
            await self.session.refresh(user)
            
            logger = __import__('logging').getLogger(__name__)
            logger.info(f"User reactivated by admin: {user.email}")
            
            return {
                "success": True,
                "user": user,
                "message": "User reactivated successfully."
            }
            
        except Exception as e:
            await self.session.rollback()
            logger = __import__('logging').getLogger(__name__)
            logger.exception("Error reactivating user")
            return {
                "success": False,
                "message": "An error occurred while reactivating the user."
            }
