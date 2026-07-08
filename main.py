import os
from typing import List
from dotenv import load_dotenv
from supabase import create_client, Client
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
import discord
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer

# =====================================================================
# PHASE 1: INITIALIZATION
# =====================================================================
load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY, DISCORD_TOKEN]):
    raise ValueError("CRITICAL ERROR: Missing configuration strings inside the .env file.")

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True 
discord_gateway_client = discord.Client(intents=intents)


# =====================================================================
# PHASE 2: DATA BLUEPRINTS
# =====================================================================
class PlayerRosterNode(BaseModel):
    """Blueprint structure for an individual team player."""
    player_discord_id: str = Field(description="The numeric Discord user ID string (extracted from the mention).")
    riot_id: str = Field(description="The complete In-Game Name / Riot ID string (e.g., Sahasya#123).")

class ExtractedFullTeamData(BaseModel):
    """Comprehensive blueprint forcing the AI to organize the entire team payload cleanly."""
    team_name: str = Field(description="The formal competitive esports team name.")
    captain_discord_id: str = Field(description="The numeric string ID of the team captain.")
    roster: List[PlayerRosterNode] = Field(description="Array list containing all parsed roster players.")
    is_valid: bool = Field(description="Set to True ONLY if the team name and at least 5 players are clearly found.")
    error_message: str = Field(description="If is_valid is False, state why and what information is missing.")


# =====================================================================
# PHASE 3: RELATIONAL DATA LOOP OPERATIONS
# =====================================================================
def commit_full_team_to_database(full_team: ExtractedFullTeamData) -> bool:
    """
    Executes a relational database transaction pipeline:
    1. Inserts the team into 'teams' table and retrieves its UUID.
    2. Maps that UUID to all roster rows and inserts them into 'players' table.
    """
    # 1. Insert Team Header Row
    team_payload = {
        "team_name": full_team.team_name,
        "captain_discord_id": full_team.captain_discord_id
    }
    team_response = supabase_client.table("teams").insert(team_payload).execute()
    
    if not team_response.data:
        raise RuntimeError("Failed to log team row node header.")
        
    inserted_team_id = team_response.data[0]["id"] # Extract the generated UUID

    # 2. Map and Insert Roster Nodes Array
    player_payloads = []
    for player in full_team.roster:
        player_payloads.append({
            "team_id": inserted_team_id, # Link via relational Foreign Key
            "player_discord_id": player.player_discord_id,
            "riot_id": player.riot_id
        })
        
    if player_payloads:
        supabase_client.table("players").insert(player_payloads).execute()
        
    return True


# =====================================================================
# PHASE 4: AGENTIC PARSING LOOP
# =====================================================================
def parse_full_registration_message(user_chat_text: str, author_id: str) -> ExtractedFullTeamData:
    """Hands complex text sentences to Gemini, returning a strictly formatted object list."""
    system_instruction = f"""
    You are the specialized Rivaro Concierge Agent. Your task is to extract the tournament team registration details and full roster profiles.
    The sender's direct Discord ID is: {author_id}. Use this as the captain_discord_id.
    
    Rules:
    1. Parse every player mentioned or listed. Extract their clean numeric Discord ID out of their mention wrapper (e.g. from <@12345> extract 12345).
    2. Extract their exact in-game Name/Riot ID tag.
    3. If there are fewer than 5 players listed or the team name is completely missing, set is_valid to False and populate the error_message.
    """

    response = ai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=user_chat_text,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=ExtractedFullTeamData,
            temperature=0.1
        ),
    )
    return ExtractedFullTeamData.model_validate_json(response.text)


# =====================================================================
# PHASE 5: LIVE WEB SOCKET NETWORK EVENT LOOPS
# =====================================================================
@discord_gateway_client.event
async def on_ready():
    print(f"\n🤖 Unified Rivaro Multi-Agent Workforce Online!")
    print(f"Connected to Gateway as: {discord_gateway_client.user}")
    print("Awaiting full team roster registrations...")

@discord_gateway_client.event
async def on_message(message):
    if message.author == discord_gateway_client.user:
        return

    if message.content.startswith("!register_team"):
        raw_user_input = message.content.replace("!register_team", "").strip()
        sender_id = str(message.author.id)
        
        await message.channel.send("⏳ *Concierge Agent is parsing your entire team roster structure...*")
        
        # Parse the structured model array
        parsed_team = parse_full_registration_message(raw_user_input, sender_id)
        
        if parsed_team.is_valid:
            try:
                # Commit relational data pipeline records
                commit_full_team_to_database(parsed_team)
                
                # Format a rich response block
                success_message = (
                    f"✅ **Team Registration Complete!**\n"
                    f"🛡️ **Team Name:** `{parsed_team.team_name}`\n"
                    f"👥 **Players Registered:** `{len(parsed_team.roster)}` players successfully synced to the database cloud tracker."
                )
                await message.channel.send(success_message)
                
            except Exception as db_err:
                await message.channel.send("❌ *Database Roster Transaction Failed.*")
                print(f"Database relational error trace: {db_err}")
        else:
            await message.channel.send(f"⚠️ **Registration Rejected:** {parsed_team.error_message}")


def run_dummy_server():
    """Spins up a lightweight web server to satisfy Render's port check requirements."""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"🌍 Dummy Health Check Server running on port {port}")
    server.serve_forever()


# =====================================================================
# PHASE 6: EXECUTION RUNTIME PIPELINE
# =====================================================================
if __name__ == "__main__":
    # Start the dummy server in a separate background thread so it doesn't block the bot
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    # Run the Discord bot client loop
    discord_gateway_client.run(DISCORD_TOKEN)