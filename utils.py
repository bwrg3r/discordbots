import json
import asyncio

file_lock = asyncio.Lock()

async def load_votes(file_path="votes.json"):
    async with file_lock:
        try:
            with open(file_path, "r") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

async def save_votes(votes, file_path="votes.json"):
    async with file_lock:
        with open(file_path, "w") as file:
            json.dump(votes, file, indent=4)
