#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(__file__))

from cogs.utils import time_data

# Test time data for JP region with edition 56
print("Testing JP region time data for edition 56:")
update, start, end, total, left, elapsed = time_data(
    update_only=True, 
    tournament_over=True, 
    edition_dir="56", 
    region="JP"
)

print(f"Update: {update}")
print(f"Start: {start}")
print(f"End: {end}")
print(f"Total: {total}")
print(f"Left: {left}")
print(f"Elapsed: {elapsed}")

if elapsed:
    print(f"Elapsed hours: {round(elapsed.total_seconds() / 3600, 2)}")