#!/bin/bash

# JBI Pipeline Monitor - Bash version
# Usage: ./scripts/pipeline_monitor.sh [--json] [--watch N]

set -e

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DB_URL="${DATABASE_URL:-postgresql://postgres:Pastibisa123@localhost:5432/anotasi_db}"
KAFKA_BROKERS="${KAFKA_BROKERS:-localhost:9092}"
COMPOSE_PROJECT="jbi-service"

# Parse arguments
JSON_OUTPUT=false
WATCH_INTERVAL=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --json)
            JSON_OUTPUT=true
            shift
            ;;
        --watch)
            WATCH_INTERVAL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--json] [--watch N]"
            exit 1
            ;;
    esac
done

# Function to get container status
get_container_status() {
    local containers=()
    
    while IFS= read -r line; do
        if [ -n "$line" ]; then
            local name=$(echo "$line" | jq -r '.Names')
            local state=$(echo "$line" | jq -r '.State')
            local health=$(echo "$line" | jq -r '.Health // "N/A"')
            local uptime=$(echo "$line" | jq -r '.Status')
            
            # Filter jbi-service containers
            if [[ "$name" =~ (api|worker|db|kafka|minio|reconciliation) ]]; then
                containers+=("{\"name\":\"$name\",\"status\":\"$state\",\"health\":\"$health\",\"uptime\":\"$uptime\",\"running\":$([ "$state" == "running" ] && echo "true" || echo "false")}")
            fi
        fi
    done < <(docker ps --format json -a 2>/dev/null || true)
    
    if [ ${#containers[@]} -eq 0 ]; then
        echo "[{\"name\":\"docker-error\",\"status\":\"error\",\"health\":\"N/A\",\"uptime\":\"\",\"running\":false}]"
    else
        printf '[%s]' "$(IFS=,; echo "${containers[*]}")"
    fi
}

# Function to get Kafka status
get_kafka_status() {
    local topics="[]"
    local consumer_groups="[]"
    local error="null"
    
    # Check if kafka container is running
    if docker ps --format json | grep -q "kafka"; then
        # Try to get topics using kafka-broker-api-versions or kafka-topics
        local kafka_topics=$(docker exec -i jbi-service-kafka-1 kafka-topics --bootstrap-server kafka:9092 --list 2>/dev/null | grep "^pipeline\." || true)
        
        if [ -n "$kafka_topics" ]; then
            local topic_array=()
            while IFS= read -r topic; do
                topic_array+=("\"$topic\"")
            done <<< "$kafka_topics"
            
            if [ ${#topic_array[@]} -gt 0 ]; then
                topics="[$(IFS=,; echo "${topic_array[*]}")]"
            fi
        fi
        
        # Consumer groups - simplified
        consumer_groups='[{"group":"detection-workers","state":"unknown","members":0,"status":"check with kafka-consumer-groups"}]'
    else
        error='"Kafka container not running"'
    fi
    
    echo "{\"topics\":$topics,\"consumer_groups\":$consumer_groups,\"error\":$error}"
}

# Function to get DB status using docker exec
get_db_status() {
    local jobs_by_status="{}"
    local stuck_jobs="[]"
    local transcript_status="{}"
    local error="null"
    
    # Check if DB container is running
    if docker ps --format json | grep -q "db"; then
        # Jobs by status
        local jobs_result=$(docker exec -i jbi-service-db-1 psql -U postgres -d anotasi_db -t -A -F"," -c "
            SELECT status, COUNT(*) 
            FROM pipeline_jobs 
            GROUP BY status 
            ORDER BY count DESC;
        " 2>/dev/null || true)
        
        if [ -n "$jobs_result" ]; then
            local jobs_obj=()
            while IFS=',' read -r status count; do
                if [ -n "$status" ] && [ -n "$count" ]; then
                    jobs_obj+=("\"$status\":$count")
                fi
            done <<< "$jobs_result"
            
            if [ ${#jobs_obj[@]} -gt 0 ]; then
                jobs_by_status="{$(IFS=,; echo "${jobs_obj[*]}")}"
            fi
        fi
        
        # Transcript status
        local transcript_result=$(docker exec -i jbi-service-db-1 psql -U postgres -d anotasi_db -t -A -F"," -c "
            SELECT COALESCE(status, 'pending'), COUNT(*) 
            FROM pipeline_transcripts 
            GROUP BY status;
        " 2>/dev/null || true)
        
        if [ -n "$transcript_result" ]; then
            local transcript_obj=()
            while IFS=',' read -r status count; do
                if [ -n "$status" ] && [ -n "$count" ]; then
                    transcript_obj+=("\"$status\":$count")
                fi
            done <<< "$transcript_result"
            
            if [ ${#transcript_obj[@]} -gt 0 ]; then
                transcript_status="{$(IFS=,; echo "${transcript_obj[*]}")}"
            fi
        fi
        
        # Stuck jobs
        local stuck_result=$(docker exec -i jbi-service-db-1 psql -U postgres -d anotasi_db -t -A -F"," -c "
            SELECT 
                id::text,
                status,
                COALESCE(current_stage, '-'),
                EXTRACT(EPOCH FROM (NOW() - updated_at))/60 as stuck_minutes
            FROM pipeline_jobs
            WHERE status IN ('DETECTING', 'TRANSCRIBING', 'CROPPING_IN_PROGRESS')
            AND (
                (status = 'DETECTING' AND updated_at < NOW() - INTERVAL '30 minutes')
                OR (status = 'TRANSCRIBING' AND updated_at < NOW() - INTERVAL '60 minutes')
                OR (status = 'CROPPING_IN_PROGRESS' AND updated_at < NOW() - INTERVAL '60 minutes')
            )
            ORDER BY updated_at ASC;
        " 2>/dev/null || true)
        
        if [ -n "$stuck_result" ]; then
            local stuck_array=()
            while IFS=',' read -r job_id status stage stuck_minutes; do
                if [ -n "$job_id" ]; then
                    stuck_array+=("{\"job_id\":\"$job_id\",\"status\":\"$status\",\"stage\":\"$stage\",\"stuck_for\":\"${stuck_minutes}m\"}")
                fi
            done <<< "$stuck_result"
            
            if [ ${#stuck_array[@]} -gt 0 ]; then
                stuck_jobs="[$(IFS=,; echo "${stuck_array[*]}")]"
            fi
        fi
    else
        error='"Database container not running"'
    fi
    
    echo "{\"jobs_by_status\":$jobs_by_status,\"stuck_jobs\":$stuck_jobs,\"transcript_status\":$transcript_status,\"error\":$error}"
}

# Function to print table format
print_table() {
    local containers=$1
    local kafka=$2
    local db=$3
    
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}           JBI Pipeline Monitor                             ${BLUE}║${NC}"
    echo -e "${BLUE}║${NC}           $(date '+%Y-%m-%d %H:%M:%S')                              ${BLUE}║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    # Container Status
    echo -e "${YELLOW}Container Status${NC}"
    echo "┌─────────────────────────────┬─────────┬────────┬──────────────────────────┐"
    printf "│ %-27s │ %-7s │ %-6s │ %-24s │\n" "Container" "Status" "Health" "Uptime"
    echo "├─────────────────────────────┼─────────┼────────┼──────────────────────────┤"
    
    echo "$containers" | jq -r '.[] | [.name, .status, .health, .uptime] | @tsv' | while IFS=$'\t' read -r name status health uptime; do
        local color="$NC"
        if [ "$status" == "running" ]; then
            color="$GREEN"
        elif [ "$status" == "exited" ] || [ "$status" == "dead" ]; then
            color="$RED"
        fi
        printf "│ %-27s │ ${color}%-7s${NC} │ %-6s │ %-24s │\n" "$name" "$status" "$health" "$uptime"
    done
    
    echo "└─────────────────────────────┴─────────┴────────┴──────────────────────────┘"
    echo ""
    
    # Kafka Topics
    echo -e "${YELLOW}Kafka Topics${NC}"
    echo "┌─────────────────────────────┬────────────┐"
    printf "│ %-27s │ %-10s │\n" "Topic" "Partitions"
    echo "├─────────────────────────────┼────────────┤"
    
    local topics=$(echo "$kafka" | jq -r '.topics[]? | [.name, "-"] | @tsv')
    if [ -n "$topics" ]; then
        echo "$topics" | while IFS=$'\t' read -r topic partitions; do
            printf "│ %-27s │ %-10s │\n" "$topic" "$partitions"
        done
    fi
    
    echo "└─────────────────────────────┴────────────┘"
    echo ""
    
    # Pipeline Jobs
    echo -e "${YELLOW}Pipeline Jobs${NC}"
    echo "┌─────────────────────────────┬───────┐"
    printf "│ %-27s │ %-5s │\n" "Status" "Count"
    echo "├─────────────────────────────┼───────┤"
    
    echo "$db" | jq -r '.jobs_by_status | to_entries[] | [.key, .value] | @tsv' | while IFS=$'\t' read -r status count; do
        local color="$NC"
        if [[ "$status" =~ (NEEDS_VOICE_ANNOTATION|READY_FOR_ANNOTATION) ]]; then
            color="$GREEN"
        elif [[ "$status" =~ (DETECTING|TRANSCRIBING|CROPPING_IN_PROGRESS) ]]; then
            color="$YELLOW"
        elif [[ "$status" =~ (FAILED|CROPPING_FAILED) ]]; then
            color="$RED"
        fi
        printf "│ ${color}%-27s${NC} │ %-5s │\n" "$status" "$count"
    done
    
    echo "└─────────────────────────────┴───────┘"
    echo ""
    
    # Transcripts
    echo -e "${YELLOW}Transcripts${NC}"
    echo "┌─────────────┬───────┐"
    printf "│ %-11s │ %-5s │\n" "Status" "Count"
    echo "├─────────────┼───────┤"
    
    echo "$db" | jq -r '.transcript_status | to_entries[] | [.key, .value] | @tsv' | while IFS=$'\t' read -r status count; do
        local color="$NC"
        if [ "$status" == "cropped" ]; then
            color="$GREEN"
        elif [ "$status" == "failed" ]; then
            color="$RED"
        else
            color="$YELLOW"
        fi
        printf "│ ${color}%-11s${NC} │ %-5s │\n" "$status" "$count"
    done
    
    echo "└─────────────┴───────┘"
    echo ""
}

# Function to print JSON format
print_json() {
    local containers=$1
    local kafka=$2
    local db=$3
    
    cat <<EOF
{
  "timestamp": "$(date -Iseconds)",
  "containers": $containers,
  "kafka": $kafka,
  "database": $db
}
EOF
}

# Main monitoring loop
run_monitor() {
    local containers=$(get_container_status)
    local kafka=$(get_kafka_status)
    local db=$(get_db_status)
    
    if [ "$JSON_OUTPUT" == true ]; then
        print_json "$containers" "$kafka" "$db"
    else
        print_table "$containers" "$kafka" "$db"
    fi
}

# Main execution
if [ "$WATCH_INTERVAL" -gt 0 ]; then
    while true; do
        clear
        run_monitor
        echo "Refreshing in ${WATCH_INTERVAL}s... (Ctrl+C to stop)"
        sleep "$WATCH_INTERVAL"
    done
else
    run_monitor
fi
