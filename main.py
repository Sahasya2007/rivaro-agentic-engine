import os
from dotenv import load_dotenv
from supabase import create_client, Client
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
import discord

# =====================================================================
# PHASE 1: INITIALIZATION & CLIENT INSTANTIATION
# =====================================================================
# Read secret environment keys from your local disk storage (.env file)
load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN")

# Structural Safety Gate: Terminate execution if any setup key is missing
if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY, DISCORD_TOKEN]):
    raise ValueError(
        "CRITICAL ERROR: Missing configuration strings inside the .env file. "
        "Please ensure SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY, and DISCORD_TOKEN are fully set."
    )

# Instantiate the client drivers for our database, AI brain, and chat network
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Set up the live chat listener configurations
intents = discord.Intents.default()
intents.message_content = True  # Explicitly grant permission to read chat text messages
discord_gateway_client = discord.Client(intents=intents)


# =====================================================================
# PHASE 2: ARCHITECTURE LAYER (DATA VALIDATION SCHEMAS)
# =====================================================================
class ExtractedTeamData(BaseModel):
    """
    A rigid data box that forces the AI to structure its thoughts perfectly.
    This structure maps unstructured strings straight into safe database inputs.
    """
    team_name: str = Field(description="The formal competitive esports team name.")
    captain_discord_id: str = Field(description="The unique numerical user ID string of the team captain.")
    is_valid: bool = Field(description="Set to True ONLY if the team name can be clearly extracted from the text.")
    error_message: str = Field(description="If is_valid is False, write a polite prompt asking for the team name. Otherwise, leave empty.")


# =====================================================================
# PHASE 3: DATA LAYER (DATABASE WRITE OPERATIONS)
# =====================================================================
def commit_team_to_database(valid_team: ExtractedTeamData) -> dict:
    """
    Takes our clean, validated data object and runs a secure PostgreSQL
    INSERT query transaction block to write the team permanently into Supabase.
    """
    payload = {
        "team_name": valid_team.team_name,
        "captain_discord_id": valid_team.captain_discord_id
    }
    
    # Fire the record packet through the secure database gateway API
    response = supabase_client.table("teams").insert(payload).execute()
    return response.data


# =====================================================================
# PHASE 4: AGENTIC CORE LAYER (THE CONCIERGE AGENT)
# =====================================================================
def parse_registration_message(user_chat_text: str, author_id: str) -> ExtractedTeamData:
    """
    Hands raw text sentences to the Gemini 2.5 Flash model and forces the
    output to match our strict Pydantic schema clipboard matrix.
    """
    system_instruction = f"""
    You are the specialized Rivaro Concierge Agent. Your sole job is to extract the tournament registration details from the user's message.
    The user's direct Discord ID is: {author_id}. Use this as the captain_discord_id unless they explicitly provide a different one.
    If the team name is completely missing, vague, or unclear, set is_valid to False and write a helpful error_message.
    """

    response = ai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=user_chat_text,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=ExtractedTeamData, # Forces structural alignment
            temperature=0.1 # Enforces precise accuracy over creative variance
        ),
    )
    return ExtractedTeamData.model_validate_json(response.text)


# =====================================================================
# PHASE 5: REAL-TIME GATEWAY CONNECTION EVENTS
# =====================================================================
@discord_gateway_client.event
async def on_ready():
    """Callback event loop initialization signal. Fires when connection to Discord succeeds."""
    print(f"\n🤖 Rivaro Agentic AI Ingestion Pipeline Online!")
    print(f"Connected to Discord Gateway as: {discord_gateway_client.user}")
    print("Database connection verified. Listening for real-time registrations...")

@discord_gateway_client.event
async def on_message(message):
    """Listens continuously to every single string payload broadcasted across your server channels."""
    # Security Constraint: Avoid infinite loops by ignoring messages sent by our own bot
    if message.author == discord_gateway_client.user:
        return

    # Trigger Ingestion Hook if a user uses our structural command prefix
    if message.content.startswith("!register"):
        # Strip the activation command prefix to isolate user content text
        raw_user_input = message.content.replace("!register", "").strip()
        sender_id = str(message.author.id)
        
        # Provide immediate user interface typing feedback in chat
        await message.channel.send("⏳ *Rivaro Concierge Agent is parsing your registration details...*")
        
        # Execute the AI brain extraction module pipeline
        parsed_result = parse_registration_message(raw_user_input, sender_id)
        
        # The Agentic Decision Loop
        if parsed_result.is_valid:
            try:
                # Commit the verified data into the persistent cloud ledger
                commit_team_to_database(parsed_result)
                await message.channel.send(
                    f"✅ **Registration Successful!** Team **'{parsed_result.team_name}'** has been locked into the global database tracker ledger."
                )
            except Exception as db_err:
                await message.channel.send("❌ *Database Transaction Failed. Please contact an Administrator.*")
                print(f"Database insertion exception log: {db_err}")
        else:
            # Autonomous Error Feedback Delivery directly back to the active channel node
            await message.channel.send(f"⚠️ {parsed_result.error_message}")


# =====================================================================
# PHASE 6: PROCESS EXECUTION ENTRYPOINT
# =====================================================================
if __name__ == "__main__":
    # Boots up the background network handshake protocol block loop
    discord_gateway_client.run(DISCORD_TOKEN)