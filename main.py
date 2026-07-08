import os
from dotenv import load_dotenv
from supabase import create_client, Client
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# =====================================================================
# PHASE 1: ENVIRONMENT & INITIALIZATION
# =====================================================================
load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    raise ValueError("CRITICAL ERROR: Missing configuration keys inside the .env file.")

# Instantiate our infrastructure connections
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)


# =====================================================================
# PHASE 2: ARCHITECTURE LAYER (DATA VALIDATION SCHEMAS)
# =====================================================================
class ExtractedTeamData(BaseModel):
    """
    Rigid structural matrix used to map unstructured user strings 
    into validated data nodes for safe database ingestion.
    """
    team_name: str = Field(description="The formal competitive esports team name.")
    captain_discord_id: str = Field(description="The unique numerical user ID string of the team captain.")
    is_valid: bool = Field(description="Set to True ONLY if the team name can be clearly extracted from the text.")
    error_message: str = Field(description="If is_valid is False, write a polite prompt asking for the team name. Otherwise, leave empty.")


# =====================================================================
# PHASE 3: DATA LAYER (DATABASE INSERTION LOGIC)
# =====================================================================
def commit_team_to_database(valid_team: ExtractedTeamData) -> dict:
    """
    Takes our clean, validated AI response data object and runs a secure
    PostgreSQL INSERT query transaction block to write it into Supabase.
    """
    payload = {
        "team_name": valid_team.team_name,
        "captain_discord_id": valid_team.captain_discord_id
    }
    
    # Execute the insert pipeline transaction over the secure web gateway API
    response = supabase_client.table("teams").insert(payload).execute()
    return response.data


# =====================================================================
# PHASE 4: AGENTIC CORE LAYER (THE CONCIERGE AGENT)
# =====================================================================
def parse_registration_message(user_chat_text: str, author_id: str) -> ExtractedTeamData:
    """
    Hands the unformatted sentence string to the Gemini 2.5 Brain 
    and forces the LLM output to match our strict blueprint data shape.
    """
    system_instruction = f"""
    You are the specialized Rivaro Concierge Agent. Your sole job is to extract the tournament registration details from the user's message.
    The user's direct Discord ID is: {author_id}. Use this as the captain_discord_id unless they explicitly tell you it belongs to someone else.
    If the team name is missing, vague, or unclear, set is_valid to False and write a helpful error_message.
    """

    response = ai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=user_chat_text,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=ExtractedTeamData,
            temperature=0.1
        ),
    )
    return ExtractedTeamData.model_validate_json(response.text)


# =====================================================================
# PHASE 5: LIVE RUNTIME TESTING GATEWAY
# =====================================================================
if __name__ == "__main__":
    print("🤖 Rivaro Agentic AI Ingestion Pipeline Online.")
    
    # Simulation: A team registers for our tournament live!
    user_chat_message = "What's up admin! Register my squad 'Rivaro Elite Esports' into the season tracker."
    user_discord_id = "774411992233"
    
    print(f"\n[LIVE TEST] New Discord Message Received: '{user_chat_message}'")
    
    # Step 1: Let the AI parse and organize the text data
    parsed_result = parse_registration_message(user_chat_message, user_discord_id)
    print(f"-> AI Processing Complete. Extraction Validity: {parsed_result.is_valid}")
    
    # Step 2: The Agentic Decision Engine
    if parsed_result.is_valid:
        print(f"-> SUCCESS: Data is clean. Attempting to write '{parsed_result.team_name}' to cloud storage...")
        try:
            # Execute the database upload pipeline
            db_receipt = commit_team_to_database(parsed_result)
            print("🚀 DATABASE SUCCESS! Transaction receipt recorded:")
            print(db_receipt)
        except Exception as err:
            print(f"❌ DATABASE FAILURE: Could not write to table. Error details: {err}")
    else:
        print(f"⚠️ REGISTRATION REJECTED: Sending automated feedback payload back to user:")
        print(f"Feedback: '{parsed_result.error_message}'")