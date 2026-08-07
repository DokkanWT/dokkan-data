#!/usr/bin/env python3
"""
Script to analyze GLB fetch data and show when top1000 was updated.
Helps identify missing data points.
"""

import json
from datetime import datetime
from pathlib import Path

def main():
    fetches_dir = Path("instances/GLB/fetches")
    config_file = fetches_dir / "config.json"
    
    # Get the last fetch number
    with open(config_file, 'r') as f:
        config = json.load(f)
        last_fetch = config.get('LAST_FETCH', 0)
    
    print(f"Analyzing {last_fetch + 1} fetch files (fetch0.json to fetch{last_fetch}.json)...\n")
    print("=" * 80)
    print(f"{'Fetch':<10} {'Timestamp':<12} {'Date & Time':<25} {'Hours Since Start':<20}")
    print("=" * 80)
    
    updates = []
    first_timestamp = None
    
    for i in range(last_fetch + 1):
        fetch_file = fetches_dir / f"fetch{i}.json"
        
        if not fetch_file.exists():
            print(f"fetch{i}.json  MISSING FILE!")
            continue
        
        with open(fetch_file, 'r') as f:
            data = json.load(f)
            timestamp = data.get('rank1000_updated_at')
            
            if timestamp:
                if first_timestamp is None:
                    first_timestamp = timestamp
                
                dt = datetime.fromtimestamp(timestamp)
                hours_since_start = (timestamp - first_timestamp) / 3600
                
                updates.append({
                    'fetch': i,
                    'timestamp': timestamp,
                    'datetime': dt,
                    'hours': hours_since_start
                })
                
                print(f"fetch{i:<5}     {timestamp:<12} {dt.strftime('%Y-%m-%d %H:%M:%S'):<25} {hours_since_start:>6.2f}h")
            else:
                print(f"fetch{i:<5}     NO rank1000_updated_at field found")
    
    print("=" * 80)
    print(f"\nTotal fetches analyzed: {last_fetch + 1}")
    print(f"Total updates found: {len(updates)}")
    
    # Check for gaps
    if len(updates) > 1:
        print("\n" + "=" * 80)
        print("TIME GAPS ANALYSIS (between consecutive fetches)")
        print("=" * 80)
        
        for i in range(1, len(updates)):
            time_gap = updates[i]['timestamp'] - updates[i-1]['timestamp']
            hours_gap = time_gap / 3600
            minutes_gap = time_gap / 60
            
            # Flag gaps larger than 2 hours
            warning = " ⚠️  LARGE GAP!" if hours_gap > 2 else ""
            
            print(f"fetch{updates[i-1]['fetch']} -> fetch{updates[i]['fetch']}: "
                  f"{hours_gap:>6.2f}h ({minutes_gap:>6.1f}min){warning}")
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        total_time = updates[-1]['timestamp'] - updates[0]['timestamp']
        print(f"Start time: {updates[0]['datetime'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"End time:   {updates[-1]['datetime'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total time span: {total_time / 3600:.2f} hours ({total_time / 86400:.2f} days)")
        print(f"Average gap between fetches: {(total_time / len(updates)) / 3600:.2f} hours")

if __name__ == "__main__":
    main()
