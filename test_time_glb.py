#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(__file__))

from cogs.utils import time_data

# Test time data for GLB region with edition 58
print("Testing GLB region time data for edition 58:")
update, start, end, total, left, elapsed = time_data(
    update_only=True, 
    tournament_over=True, 
    edition_dir="58", 
    region="GLB"
)

print(f"Update: {update}")
print(f"Start: {start}")
print(f"End: {end}")
print(f"Total: {total}")
print(f"Left: {left}")
print(f"Elapsed: {elapsed}")

if elapsed:
    print(f"Elapsed hours: {round(elapsed.total_seconds() / 3600, 2)}")