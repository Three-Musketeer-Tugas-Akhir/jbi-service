import asyncio
import os
import json

# Setup the environment string from python
async def main():
    print("Please run this query on your server and give me the output:")
    print("""
psql -U postgres -d jbi_db -c "
SELECT id, segment_id, status, utterance_corrections 
FROM annotation_edits 
WHERE segment_id IN (
    SELECT id FROM pipeline_segments WHERE job_id = 'b458a235-94b6-4c6e-be35-a86d9975360e'
);
"
""")
main()
