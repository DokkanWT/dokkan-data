#!/bin/bash

# Launch script for Dokkan Tournament Bot
# Provides options to launch different components with process management

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to check if a process is running
is_process_running() {
    local process_name="$1"
    local search_pattern="$2"
    
    if pgrep -f "$search_pattern" > /dev/null; then
        return 0  # Process is running
    else
        return 1  # Process is not running
    fi
}

# Function to start the bot
start_bot() {
    echo -e "${BLUE}Checking bot status...${NC}"
    
    if is_process_running "bot" "cli_main.py"; then
        echo -e "${YELLOW}Bot is already running!${NC}"
        return
    fi
    
    echo -e "${GREEN}Starting bot in background...${NC}"
    nohup python3 cli_main.py > bot.log 2>&1 &
    echo "Bot started with PID: $!"
    echo -e "${GREEN}Log file: bot.log${NC}"
}

# Function to start fetches for both regions
start_fetches() {
    echo -e "${BLUE}Checking fetch processes...${NC}"
    
    # Check JP fetches
    if is_process_running "fetch_jp" "fetch_and_save.py.*--JP"; then
        echo -e "${YELLOW}JP fetches are already running!${NC}"
    else
        echo -e "${GREEN}Starting JP fetches in background...${NC}"
        nohup python3 fetch_and_save.py --JP > fetch_jp.log 2>&1 &
        echo "JP fetches started with PID: $!"
    fi
    
    # Check GLB fetches
    if is_process_running "fetch_glb" "fetch_and_save.py.*--GLB"; then
        echo -e "${YELLOW}GLB fetches are already running!${NC}"
    else
        echo -e "${GREEN}Starting GLB fetches in background...${NC}"
        nohup python3 fetch_and_save.py --GLB > fetch_glb.log 2>&1 &
        echo "GLB fetches started with PID: $!"
    fi
    
    echo -e "${GREEN}Log files: fetch_jp.log, fetch_glb.log${NC}"
}

# Function to start web server
start_web() {
    echo -e "${BLUE}Checking web server status...${NC}"
    
    if is_process_running "web" "app.py"; then
        echo -e "${YELLOW}Web server is already running!${NC}"
        return
    fi
    
    echo -e "${GREEN}Starting web server in background...${NC}"
    # Change to WT_Web directory and start the app
    cd WT_Web
    nohup python3 app.py > ../web.log 2>&1 &
    echo "Web server started with PID: $!"
    cd ..
    echo -e "${GREEN}Log file: web.log${NC}"
}

# Function to show status of all processes
show_status() {
    echo -e "${BLUE}=== Process Status ===${NC}"
    
    # Check bot
    if is_process_running "bot" "cli_main.py"; then
        echo -e "${GREEN}✓ Bot: Running${NC}"
    else
        echo -e "${RED}✗ Bot: Not running${NC}"
    fi
    
    # Check JP fetches
    if is_process_running "fetch_jp" "fetch_and_save.py.*--JP"; then
        echo -e "${GREEN}✓ JP Fetches: Running${NC}"
    else
        echo -e "${RED}✗ JP Fetches: Not running${NC}"
    fi
    
    # Check GLB fetches
    if is_process_running "fetch_glb" "fetch_and_save.py.*--GLB"; then
        echo -e "${GREEN}✓ GLB Fetches: Running${NC}"
    else
        echo -e "${RED}✗ GLB Fetches: Not running${NC}"
    fi
    
    # Check web server
    if is_process_running "web" "app.py"; then
        echo -e "${GREEN}✓ Web Server: Running${NC}"
    else
        echo -e "${RED}✗ Web Server: Not running${NC}"
    fi
    echo ""
}

# Main menu
show_menu() {
    echo -e "${BLUE}=== Dokkan Tournament Bot Launcher ===${NC}"
    echo ""
    show_status
    echo "1. Launch Bot (cli_main.py)"
    echo "2. Launch Fetches (both JP and GLB)"
    echo "3. Launch Web Server (WT_Web/app.py)"
    echo "4. Show Process Status"
    echo "5. Quit"
    echo ""
    echo -n "Select an option (1-5): "
}

# Main loop
while true; do
    show_menu
    read -r choice
    
    case $choice in
        1)
            echo ""
            start_bot
            echo ""
            read -p "Press Enter to continue..."
            ;;
        2)
            echo ""
            start_fetches
            echo ""
            read -p "Press Enter to continue..."
            ;;
        3)
            echo ""
            start_web
            echo ""
            read -p "Press Enter to continue..."
            ;;
        4)
            echo ""
            show_status
            read -p "Press Enter to continue..."
            ;;
        5)
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option. Please select 1-5.${NC}"
            sleep 1
            ;;
    esac
    
    # Clear screen for next iteration
    clear
done