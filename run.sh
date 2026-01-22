#!/usr/bin/env bash
#
# MARTIN Telegram Trading Bot - Bootstrap Script
#
# This script provides one-command startup:
#   1. Creates Python virtual environment if missing
#   2. Installs dependencies from requirements.txt
#   3. Runs MARTIN
#
# Usage:
#   ./run.sh
#
# The script is idempotent - safe to run multiple times.
# .env file in project root is automatically loaded by the application.
#

set -e

# Script directory (project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
VENV_DIR=".venv"
PYTHON_MIN_VERSION="3.11"
REQUIREMENTS_FILE="requirements.txt"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check Python version
check_python() {
    local python_cmd=""
    
    # Try python3 first, then python
    if command -v python3 &> /dev/null; then
        python_cmd="python3"
    elif command -v python &> /dev/null; then
        python_cmd="python"
    else
        log_error "Python not found. Please install Python ${PYTHON_MIN_VERSION} or higher."
        exit 1
    fi
    
    # Check version
    local version
    version=$($python_cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)
    
    if [[ "$major" -lt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -lt 11 ]]; }; then
        log_error "Python ${PYTHON_MIN_VERSION} or higher is required. Found: $version"
        exit 1
    fi
    
    echo "$python_cmd"
}

# Create virtual environment if it doesn't exist
create_venv() {
    local python_cmd="$1"
    
    if [[ -d "$VENV_DIR" ]]; then
        log_info "Virtual environment already exists at $VENV_DIR"
    else
        log_info "Creating virtual environment at $VENV_DIR..."
        $python_cmd -m venv "$VENV_DIR"
        log_info "Virtual environment created."
    fi
}

# Activate virtual environment
activate_venv() {
    if [[ -f "$VENV_DIR/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
        log_info "Virtual environment activated."
    else
        log_error "Virtual environment activation script not found."
        exit 1
    fi
}

# Install dependencies
install_dependencies() {
    if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
        log_error "Requirements file not found: $REQUIREMENTS_FILE"
        exit 1
    fi
    
    # Check if we need to install/update dependencies
    # Using a hash of requirements.txt to detect changes
    local hash_file="$VENV_DIR/.requirements_hash"
    local current_hash
    current_hash=$(md5sum "$REQUIREMENTS_FILE" | cut -d' ' -f1)
    
    if [[ -f "$hash_file" ]]; then
        local stored_hash
        stored_hash=$(cat "$hash_file")
        if [[ "$current_hash" == "$stored_hash" ]]; then
            log_info "Dependencies are up to date."
            return 0
        fi
    fi
    
    log_info "Installing dependencies from $REQUIREMENTS_FILE..."
    pip install --quiet --upgrade pip
    pip install --quiet -r "$REQUIREMENTS_FILE"
    
    # Store the hash
    echo "$current_hash" > "$hash_file"
    log_info "Dependencies installed."
}

# Create data directory if needed
create_data_dir() {
    if [[ ! -d "data" ]]; then
        log_info "Creating data directory..."
        mkdir -p "data"
    fi
}

# Check for .env file
check_env_file() {
    if [[ ! -f ".env" ]]; then
        if [[ -f ".env.example" ]]; then
            log_warn "No .env file found. Copy .env.example to .env and configure it:"
            log_warn "  cp .env.example .env"
            log_warn "  # Edit .env with your settings"
        else
            log_warn "No .env file found. MARTIN will use environment variables."
            log_warn "Required: TELEGRAM_BOT_TOKEN"
        fi
    else
        log_info ".env file found - will be loaded automatically."
    fi
}

# Run MARTIN
run_martin() {
    log_info "Starting MARTIN..."
    echo ""
    python -m src.main
}

# Main
main() {
    echo "========================================"
    echo "  MARTIN Telegram Trading Bot"
    echo "========================================"
    echo ""
    
    # Check Python
    local python_cmd
    python_cmd=$(check_python)
    log_info "Using Python: $python_cmd"
    
    # Create and activate virtual environment
    create_venv "$python_cmd"
    activate_venv
    
    # Install dependencies
    install_dependencies
    
    # Create data directory
    create_data_dir
    
    # Check .env
    check_env_file
    
    echo ""
    echo "========================================"
    echo ""
    
    # Run MARTIN
    run_martin
}

main "$@"
