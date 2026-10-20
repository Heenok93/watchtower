# WATCHTOWER agent: automatic scientific surveillance

this app takes prompts and a selection of RSS feeds as inputs, retrieves articles fulfilling search criteria
and automatically score pertinence. A local small LLM (Qwen-light, xx, yyy) judges the filtered articles and 
record the most pertinent ones in a SQLite database.


