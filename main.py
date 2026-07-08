import os
from typing import List, Dict
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

# Short-term session memory mapping
REGISTRATION_STATES: Dict[str, dict] = {}


# =====================================================================
# PHASE 2: DATA STRUCTURE SCHEMAS
# =====================================================================
class SimplePlayerNode(BaseModel):
    """Rigid blueprint for player details."""
    riot_id: str = Field(description="The complete In-Game Name / Riot ID string (e.g., Sahasya#123).")
    rank: str = Field(description="The competitive rank of the player (e.g., Diamond 2).")

class ExtractedRosterData(BaseModel):
    """Blueprint forcing the AI to validate the entire roster list."""
    players: List[SimplePlayerNode] = Field(description="Array list of all 5 parsed players.")
    is_valid: bool = Field(description="Set to True ONLY if at least 5 distinct players with Riot IDs and ranks are found.")
    error_message: str = Field(description="If is_valid is False, state clearly what went wrong with the roster text layout.")


# =====================================================================
# PHASE 3: DATABASE RELATIONAL LAYERS
# =====================================================================
def commit_simplified_team_to_db(captain_id: str, team_name: str, roster_list: List[SimplePlayerNode]) -> bool:
    """Inserts team header records, grabs the UUID, and injects player nodes array."""
    # 1. Store Team Header Row
    team_payload = {
        "team_name": team_name,
        "captain_discord_id": captain_id
    }
    team_response = supabase_client.table("teams").insert(team_payload).execute()
    
    if not team_response.data:
        raise RuntimeError("Database insertion failed.")
        
    inserted_team_id = team_response.data[0]["id"]

    # 2. Map and Insert Player Records with placeholder player_discord_id values
    player_payloads = []
    for player in roster_list:
        player_payloads.append({
            "team_id": inserted_team_id,
            "player_discord_id": "NOT_PROVIDED",  # Explicit fallback string
            "riot_id": player.riot_id,
            "rank": player.rank
        })
        
    if player_payloads:
        supabase_client.table("players").insert(player_payloads).execute()
        
    return True


# =====================================================================
# PHASE 4: AGENTIC INTERPRETATION MATRIX
# =====================================================================
def parse_text_roster_list(user_raw_text: str) -> ExtractedRosterData:
    """Uses Gemini 2.5 Flash to automatically extract data tokens from the list layout."""
    system_instruction = """
    You are the specialized Rivaro Roster Evaluator. Your sole job is to clean and extract player accounts and ranks from a text list.
    
    Rules:
    1. Look for the player's In-Game Name / Riot ID. Ensure it contains a '#' separator tag.
    2. Extract their competitive rank mentioned next to or near their name.
    3. If there are fewer than 5 valid players parsed, set is_valid to False and write a helpful error_message.
    """
    response = ai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=user_raw_text,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=ExtractedRosterData,
            temperature=0.1
        ),
    )
    return ExtractedRosterData.model_validate_json(response.text)


# =====================================================================
# PHASE 5: EVENT HANDLERS
# =====================================================================
@discord_gateway_client.event
async def on_ready():
    print(f"\n🤖 Rivaro Clean Registration Engine Online!")
    print(f"Connected to Gateway as: {discord_gateway_client.user}")

@discord_gateway_client.event
async def on_message(message):
    if message.author == discord_gateway_client.user:
        return

    user_id = str(message.author.id)

    # Command Trigger Initializer
    if message.content.startswith("!register_team"):
        if user_id in REGISTRATION_STATES:
            await message.channel.send("⚠️ You are already registering a team! Type `!cancel` to close it.")
            return
            
        REGISTRATION_STATES[user_id] = {
            "step": "AWAITING_TEAM_NAME",
            "team_name": ""
        }
        await message.channel.send("🛡️ **Rivaro Season 2 Registration Started!**\nWhat is your official **Team Name**?")
        return

    # Cancel Catch
    if message.content == "!cancel" and user_id in REGISTRATION_STATES:
        del REGISTRATION_STATES[user_id]
        await message.channel.send("🛑 *Registration sequence canceled cleanly.*")
        return

    # Conversation State Core Router
    if user_id in REGISTRATION_STATES:
        session = REGISTRATION_STATES[user_id]

        # STEP 1: Process Team Name
        if session["step"] == "AWAITING_TEAM_NAME":
            cleaned_name = message.content.strip()
            if len(cleaned_name) < 2:
                await message.channel.send("⚠️ Name too short! Enter a valid team name:")
                return
                
            session["team_name"] = cleaned_name
            session["step"] = "AWAITING_ROSTER_TEXT"
            
            guide_prompt = (
                f"✅ Team Name saved as `{cleaned_name}`.\n\n"
                f"📝 **Roster Collection:**\n"
                f"Please type out your **5 players** with their **Riot ID** and **Rank** on separate lines. "
                f"Example format:\n"
                f"```text\n"
                f"1. Sahasya#123 - Radiant\n"
                f"2. Nishanth#456 - Diamond 2\n"
                f"3. Vivek#789 - Ascendant 1\n"
                f"4. Dhinesh#000 - Immortal 1\n"
                f"5. PlayerFive#555 - Gold 3\n"
                f"```"
            )
            await message.channel.send(guide_prompt)
            return

        # STEP 2: Process Roster Block with Gemini AI Core
        if session["step"] == "AWAITING_ROSTER_TEXT":
            await message.channel.send("⏳ *Rivaro Agent is processing and verifying your roster list...*")
            
            # Fire the token breakdown parser routine
            parsed_roster = parse_text_roster_list(message.content)
            
            if parsed_roster.is_valid:
                try:
                    # Write relational record sets directly to PostgreSQL database
                    commit_simplified_team_to_db(user_id, session["team_name"], parsed_roster.players)
                    await message.channel.send(
                        f"🎉 **Registration Successful!**\n"
                        f"🛡️ Team **'{session['team_name']}'** has been successfully cataloged.\n"
                        f"All 5 player slots and ranks have been locked into your Supabase ledger cloud rows!"
                    )
                except Exception as e:
                    await message.channel.send("❌ *Database transaction error occurred writing rows.*")
                    print(f"Database insertion error: {e}")
                finally:
                    del REGISTRATION_STATES[user_id]
            else:
                await message.channel.send(
                    f"⚠️ **Roster Parsing Failed:** {parsed_roster.error_message}\n"
                    f"Please re-enter your 5-player list following the guide format:"
                )


# =====================================================================
# PORT SERVER BINDING DAEMON
# =====================================================================
def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    discord_gateway_client.run(DISCORD_TOKEN)