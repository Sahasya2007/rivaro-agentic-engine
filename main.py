import os
from dotenv import load_dotenv
from supabase import create_client, Client
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# =====================================================================
# PHASE 1: ENVIRONMENT & INITIALIZATION
# =====================================================================
# Load the secret keys from the local .env file securely into runtime memory
load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")

# Safety Gate: Terminate execution immediately if secrets are missing
if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    raise ValueError(
        "CRITICAL ERROR: Missing configuration keys inside the .env file. "
        "Please check your SUPABASE_URL, SUPABASE_KEY, and GEMINI_API_KEY values."
    )

# Instantiate our backend infrastructure API client drivers
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)


# =====================================================================
# PHASE 2: ARCHITECTURE LAYER (DATA VALIDATION SCHEMAS)
# =====================================================================
class ExtractedTeamData(BaseModel):
    """
    A rigid structured data schema model. This defines the exact format
    the AI must organize its thoughts into before writing to our database.
    """
    team_name: str = Field(description="The formal competitive esports team name.")
    captain_discord_id: str = Field(description="The unique numerical user ID string of the team captain.")
    is_valid: bool = Field(description="Set to True ONLY if the team name can be clearly extracted from the text.")
    error_message: str = Field(description="If is_valid is False, write a polite prompt asking for the team name. Otherwise, leave empty.")


# =====================================================================
# PHASE 3: AGENTIC CORE LAYER (THE CONCIERGE AGENT)
# =====================================================================
def parse_registration_message(user_chat_text: str, author_id: str) -> ExtractedTeamData:
    """
    Takes unformatted Discord chat sentences, passes them into the Gemini 2.5 Brain,
    and forces the LLM to map the data attributes cleanly into our data schema model.
    """
    
    system_instruction = f"""
    You are the specialized Rivaro Concierge Agent. Your sole job is to extract the tournament registration details from the user's message.
    The user's direct Discord ID is: {author_id}. Use this as the captain_discord_id unless they explicitly tell you it belongs to someone else.
    If the team name is missing, vague, or unclear, set is_valid to False and write a helpful error_message.
    """

    # Query the high-velocity Gemini 2.5 Flash model with strict JSON schema constraints
    response = ai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=user_chat_text,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=ExtractedTeamData, # Enforces strict data shape output
            temperature=0.1 # Forces deterministic accuracy over random creativity
        ),
    )
    
    # Validate the raw AI string back into a manageable python data object
    return ExtractedTeamData.model_validate_json(response.text)


# =====================================================================
# PHASE 4: EXECUTION RUNTIME GATEWAY
# =====================================================================
if __name__ == "__main__":
    print("🤖 Rivaro Agentic AI Ingestion Pipeline Online.")
    print("Database connection parameters verified.")
    
    # --- RUN SIMULATION 1: A PERFECT REGISTRATION INPUT ---
    mock_chat_1 = "Yo! Please register our lineup called Rivaro Alpha Squad immediately."
    mock_discord_id_1 = "228844661100"
    
    print(f"\n[SIMULATION 1] Incoming Message: '{mock_chat_1}'")
    
    # Process through our Concierge Agent
    result_1 = parse_registration_message(mock_chat_1, mock_discord_id_1)
    
    print("--- Ingestion Log Trace ---")
    print(f"Is Entry Valid: {result_1.is_valid}")
    print(f"Extracted Team Name: '{result_1.team_name}'")
    print(f"Assigned Captain ID: {result_1.captain_discord_id}")
    print(f"Agent Response Context: {result_1.error_message}")

    print("\n" + "="*50 + "\n")

    # --- RUN SIMULATION 2: AN ERROR HANDLING INPUT (MISSING TEAM NAME) ---
    mock_chat_2 = "Hey admin bot! Sign me up for the upcoming tournament right now!"
    mock_discord_id_2 = "995511337744"
    
    print(f"[SIMULATION 2] Incoming Message: '{mock_chat_2}'")
    
    # Process through our Concierge Agent
    result_2 = parse_registration_message(mock_chat_2, mock_discord_id_2)
    
    print("--- Ingestion Log Trace ---")
    print(f"Is Entry Valid: {result_2.is_valid}")
    print(f"Extracted Team Name: '{result_2.team_name}'")
    print(f"Assigned Captain ID: {result_2.captain_discord_id}")
    print(f"Agent Self-Correction Response: {result_2.error_message}")