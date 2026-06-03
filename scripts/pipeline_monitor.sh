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

# Function to get active jobs from docker logs
get_active_jobs_from_logs() {
    local active_jobs="[]"
    local job_array=()
    
    # Check detection worker logs (look for "Processing detection job:" or "Processing detect job:")
    local detection_logs=$(docker logs --tail 100 jbi-service-detection-worker-1 2>/dev/null | grep -oP 'Processing (detection|detect) job[:\s]+\K[0-9a-fA-F-]{36}' | tail -1)
    if [ -n "$detection_logs" ]; then
        job_array+=("{\"worker\":\"detection-worker\",\"job_id\":\"$detection_logs\",\"stage\":\"detection\"}")
    fi
    
    # Check ASR worker logs (look for "Processing asr job:" or "Processing ASR job:")
    local asr_logs=$(docker logs --tail 100 jbi-service-asr-worker-1 2>/dev/null | grep -oP 'Processing (asr|ASR) job[:\s]+\K[0-9a-fA-F-]{36}' | tail -1)
    if [ -n "$asr_logs" ]; then
        job_array+=("{\"worker\":\"asr-worker\",\"job_id\":\"$asr_logs\",\"stage\":\"asr\"}")
    fi
    
    # Check cropping worker logs
    local cropping_logs=$(docker logs --tail 100 jbi-service-cropping-worker-1 2>/dev/null | grep -oP 'Starting cropping stage for job[:\s]+\K[0-9a-fA-F-]{36}' | tail -1)
    if [ -n "$cropping_logs" ]; then
        job_array+=("{\"worker\":\"cropping-worker\",\"job_id\":\"$cropping_logs\",\"stage\":\"cropping\"}")
    fi
    
    if [ ${#job_array[@]} -gt 0 ]; then
        active_jobs="[$(IFS=,; echo "${job_array[*]}")]"
    fi
    
    echo "$active_jobs"
}

# Function to get Kafka status
get_kafka_status() {
    local topics="[]"
    local consumer_groups="[]"
    local worker_activity="[]"
    local error="null"
    
    # Check if kafka container is running
    if docker ps --format json | grep -q "kafka"; then
        # Try to get topics using kafka-topics
        local kafka_topics_output=$(docker exec -i jbi-service-kafka-1 kafka-topics --bootstrap-server kafka:9092 --list 2>/dev/null | grep "^pipeline\." || true)
        
        if [ -n "$kafka_topics_output" ]; then
            local topic_array=()
            while IFS= read -r topic; do
                if [ -n "$topic" ]; then
                    topic_array+=("{\"name\":\"$topic\",\"partitions\":\"-\"}")
                fi
            done <<< "$kafka_topics_output"
            
            if [ ${#topic_array[@]} -gt 0 ]; then
                topics="[$(IFS=,; echo "${topic_array[*]}")]"
            fi
        fi
        
        # Check consumer groups and worker activity
        local cg_array=()
        local activity_array=()
        local groups=("detection-workers" "asr-workers" "cropping-workers")
        local topics_map=("pipeline.jobs.detect" "pipeline.jobs.asr" "pipeline.jobs.crop")
        
        for i in "${!groups[@]}"; do
            local group="${groups[$i]}"
            local topic="${topics_map[$i]}"
            local worker_name=""
            case "$group" in
                "detection-workers") worker_name="detection-worker" ;;
                "asr-workers") worker_name="asr-worker" ;;
                "cropping-workers") worker_name="cropping-worker" ;;
            esac
            
            # Get consumer group details
            local cg_info=$(docker exec -i jbi-service-kafka-1 kafka-consumer-groups --bootstrap-server kafka:9092 --describe --group "$group" 2>/dev/null || true)
            
            local members=0
            local total_lag=0
            local state="unknown"
            
            if [ -n "$cg_info" ]; then
                # Check if group has active members
                if echo "$cg_info" | grep -q "has no active members"; then
                    members=0
                    state="Stable"
                else
                    members=$(echo "$cg_info" | grep -c "^$group" || echo "0")
                    state="Stable"
                fi
                
                # Calculate total lag
                total_lag=$(echo "$cg_info" | awk '/^'$group'/ {sum+=$5} END {print sum+0}')
            fi
            
            # Determine worker activity
            local activity="idle"
            local activity_color="yellow"
            
            if [ "$members" -gt 0 ] && [ "$total_lag" -gt 0 ]; then
                activity="processing"
                activity_color="green"
            elif [ "$members" -eq 0 ] && [ "$total_lag" -gt 0 ]; then
                activity="down (lag: $total_lag)"
                activity_color="red"
            elif [ "$members" -gt 0 ] && [ "$total_lag" -eq 0 ]; then
                activity="idle (connected)"
                activity_color="yellow"
            fi
            
            cg_array+=("{\"group\":\"$group\",\"state\":\"$state\",\"members\":$members,\"lag\":$total_lag,\"status\":\"$activity\"}")
            activity_array+=("{\"worker\":\"$worker_name\",\"activity\":\"$activity\",\"lag\":$total_lag}")
        done
        
        if [ ${#cg_array[@]} -gt 0 ]; then
            consumer_groups="[$(IFS=,; echo "${cg_array[*]}")]"
        fi
        
        if [ ${#activity_array[@]} -gt 0 ]; then
            worker_activity="[$(IFS=,; echo "${activity_array[*]}")]"
        fi
    else
        error='"Kafka container not running"'
    fi
    
    echo "{\"topics\":$topics,\"consumer_groups\":$consumer_groups,\"worker_activity\":$worker_activity,\"error\":$error}"
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
        # Active jobs (currently being processed)
        local active_result=$(docker exec -i jbi-service-db-1 psql -U postgres -d anotasi_db -t -A -F"," -c "
            SELECT 
                id::text,
                status,
                COALESCE(current_stage, '-'),
                COALESCE(original_filename, 'unknown'),
                EXTRACT(EPOCH FROM (NOW() - updated_at))/60 as running_minutes
            FROM pipeline_jobs
            WHERE status IN ('DETECTING', 'TRANSCRIBING', 'CROPPING_IN_PROGRESS')
            ORDER BY updated_at DESC
            LIMIT 10;
        " 2>/dev/null || true)
        
        local active_jobs="[]"
        if [ -n "$active_result" ]; then
            local active_array=()
            while IFS=',' read -r job_id status stage filename running_minutes; do
                if [ -n "$job_id" ]; then
                    # Determine which worker is processing this
                    local worker="unknown"
                    case "$status" in
                        "DETECTING") worker="detection-worker" ;;
                        "TRANSCRIBING") worker="asr-worker" ;;
                        "CROPPING_IN_PROGRESS") worker="cropping-worker" ;;
                    esac
                    active_array+=("{\"job_id\":\"$job_id\",\"status\":\"$status\",\"stage\":\"$stage\",\"worker\":\"$worker\",\"filename\":\"$filename\",\"running_for\":\"${running_minutes}m\"}")
                fi
            done <<< "$active_result"
            
            if [ ${#active_array[@]} -gt 0 ]; then
                active_jobs="[$(IFS=,; echo "${active_array[*]}")]"
            fi
        fi
    else
        error='"Database container not running"'
    fi
    
    echo "{\"jobs_by_status\":$jobs_by_status,\"active_jobs\":$active_jobs,\"stuck_jobs\":$stuck_jobs,\"transcript_status\":$transcript_status,\"error\":$error}"
}

# Function to print table format
print_table() {
    local containers=$1
    local kafka=$2
    local db=$3
    local logs=$4
    
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
    
    # Worker Activity
    echo -e "${YELLOW}Worker Activity${NC}"
    echo "┌─────────────────────────────┬──────────────────────────┬─────────────┐"
    printf "│ %-27s │ %-24s │ %-11s │\n" "Worker" "Activity" "Queue Lag"
    echo "├─────────────────────────────┼──────────────────────────┼─────────────┤"
    
    echo "$kafka" | jq -r '.worker_activity[]? | [.worker, .activity, .lag] | @tsv' | while IFS=$'\t' read -r worker activity lag; do
        local color="$NC"
        if [[ "$activity" =~ processing ]]; then
            color="$GREEN"
        elif [[ "$activity" =~ down ]]; then
            color="$RED"
        elif [[ "$activity" =~ idle ]]; then
            color="$YELLOW"
        fi
        printf "│ %-27s │ ${color}%-24s${NC} │ %-11s │\n" "$worker" "$activity" "$lag"
    done
    
    echo "└─────────────────────────────┴──────────────────────────┴─────────────┘"
    echo ""
    
    # Active Jobs from Docker Logs
    local log_jobs=$(echo "$logs" | jq -r '.[]? | [.worker, .job_id[:8], .stage] | @tsv')
    if [ -n "$log_jobs" ]; then
        echo -e "${YELLOW}Active Jobs (from Docker Logs)${NC}"
        echo "┌─────────────────────────────┬──────────┬──────────────────┐"
        printf "│ %-27s │ %-8s │ %-16s │\n" "Worker" "Job ID" "Stage"
        echo "├─────────────────────────────┼──────────┼──────────────────┤"
        
        echo "$log_jobs" | while IFS=$'\t' read -r worker job_id stage; do
            printf "│ %-27s │ %-8s │ %-16s │\n" "$worker" "$job_id" "$stage"
        done
        
        echo "└─────────────────────────────┴──────────┴──────────────────┘"
        echo ""
    fi
    
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
    local logs=$4
    
    cat <<EOF
{
  "timestamp": "$(date -Iseconds)",
  "containers": $containers,
  "kafka": $kafka,
  "database": $db,
  "active_jobs_from_logs": $logs
}
EOF
}

# Main monitoring loop
run_monitor() {
    local containers=$(get_container_status)
    local kafka=$(get_kafka_status)
    local db=$(get_db_status)
    local logs=$(get_active_jobs_from_logs)
    
    if [ "$JSON_OUTPUT" == true ]; then
        print_json "$containers" "$kafka" "$db" "$logs"
    else
        print_table "$containers" "$kafka" "$db" "$logs"
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
