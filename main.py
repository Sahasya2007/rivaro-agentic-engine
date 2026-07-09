import os
import re
import random
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
# PHASE 1: INITIALIZATION & SERVER HOOKS
# =====================================================================
load_dotenv()

# 🎛️ DYNAMIC CLOUD CONFIGURATION INTERFACE
TOURNAMENT_MODE: str = os.getenv("TOURNAMENT_MODE", "FREE").upper()

SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN")

CUSTOM_GREETING: str = os.getenv(
    "REGISTRATION_GREETING", 
    "🛡️ **Registration Started!**\n\nPlease reply with your **Team Name** and **Leader's Phone Number** separated by a comma.\n*Example: Team Solitude, 9876543210*"
)

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY, DISCORD_TOKEN]):
    raise ValueError("CRITICAL ERROR: Missing configuration strings inside the .env file.")

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True 
discord_gateway_client = discord.Client(intents=intents)

REGISTRATION_STATES: Dict[str, dict] = {}

VALORANT_RANK_WEIGHTS: Dict[str, int] = {
    "iron": 1, "bronze": 2, "silver": 3, "gold": 4, 
    "platinum": 5, "diamond": 6, "ascendant": 7, 
    "immortal": 8, "radiant": 9, "unrated": 3
}


# =====================================================================
# PHASE 2: PARSING BLOCK SCHEMAS (DATA VALIDATION MATRIX)
# =====================================================================
class SimplePlayerNode(BaseModel):
    """Rigid blueprint structure for an individual team player."""
    riot_id: str = Field(description="The complete In-Game Name / Riot ID string (e.g., Phantom#999).")
    rank: str = Field(description="The competitive rank of the player (e.g., Gold 2).")

class ExtractedRosterData(BaseModel):
    """Comprehensive validation blueprint forcing the AI to format array nodes uniformly."""
    players: List[SimplePlayerNode] = Field(description="Array list of all 5 parsed players.")
    is_valid: bool = Field(description="Set to True ONLY if at least 5 distinct players with Riot IDs and ranks are found.")
    error_message: str = Field(description="If is_valid is False, state clearly what went wrong with the roster text layout.")


# =====================================================================
# PHASE 3: DATABASE RELATIONAL LAYERS (TEAMS, PLAYERS & MATCHES)
# =====================================================================
def commit_simplified_team_to_db(captain_id: str, team_name: str, phone_number: str, roster_list: List[SimplePlayerNode]) -> bool:
    """Inserts team header details dynamically based on global tournament operational parameters."""
    if TOURNAMENT_MODE == "FREE":
        init_verification = True
        init_payment = "FREE_ENTRY"
    else:
        init_verification = False
        init_payment = "PENDING"

    team_payload = {
        "team_name": team_name,
        "captain_discord_id": captain_id,
        "leader_phone": phone_number,
        "is_verified": init_verification,
        "payment_status": init_payment
    }
    team_response = supabase_client.table("teams").insert(team_payload).execute()
    
    if not team_response.data:
        raise RuntimeError("Database tracking team insertion rejected.")
        
    inserted_team_id = team_response.data[0]["team_id"]

    player_payload = {
        "team_id": inserted_team_id,
        "player_1": f"{roster_list[0].riot_id} - {roster_list[0].rank}",
        "player_2": f"{roster_list[1].riot_id} - {roster_list[1].rank}",
        "player_3": f"{roster_list[2].riot_id} - {roster_list[2].rank}",
        "player_4": f"{roster_list[3].riot_id} - {roster_list[3].rank}",
        "player_5": f"{roster_list[4].riot_id} - {roster_list[4].rank}"
    }
    
    supabase_client.table("players").insert(player_payload).execute()
    return True


# =====================================================================
# PHASE 4: AGENTIC TOKEN EXTRACTION ROUTINES (LLM HANDSHAKE)
# =====================================================================
def parse_text_roster_list(user_raw_text: str) -> ExtractedRosterData:
    """Uses Gemini 2.5 Flash to automatically extract clean structures from raw human lists."""
    system_instruction = """
    You are the specialized Roster Evaluator. Your sole job is to clean and extract player accounts and ranks from a text list.
    
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
# PHASE 5: LIVE GATEWAY NETWORK INTERCEPTORS (DISCORD LOOPS)
# =====================================================================
@discord_gateway_client.event
async def on_ready():
    print(f"\n🤖 Dynamic Tournament Infrastructure Engine Online!")
    print(f"Loaded Cloud Format Context: [{TOURNAMENT_MODE}]")
    print(f"Connected to Gateway as: {discord_gateway_client.user}")


@discord_gateway_client.event
async def on_message(message):
    if message.author == discord_gateway_client.user:
        return

    user_id = str(message.author.id)

    # ⚔️ SECURITY CONTROLLED AUTOMATED MATCHMAKING GENERATOR (ADMINS ONLY)
    if message.content.startswith("!generate_matches") or message.content.startswith("!generate_teams"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❌ **Access Denied:** Only tournament administrators can generate brackets.")
            return

        status_msg = await message.channel.send("⚖️ *Filtering eligible tournament rosters and calculating fair bracket pairings...*")

        # Fetches only teams marked True (Free mode handles this automatically at signup)
        teams_res = supabase_client.table("teams").select("team_id, team_name, captain_discord_id").eq("is_verified", True).execute()
        players_res = supabase_client.table("players").select("team_id, player_1, player_2, player_3, player_4, player_5").execute()

        all_teams = teams_res.data
        all_players = {row["team_id"]: row for row in players_res.data}

        if len(all_teams) < 2:
            await status_msg.edit(content="⚠️ Matchmaking pool empty. You need at least **2 APPROVED/VERIFIED** teams inside your database pool!")
            return

        team_skill_manifest = []
        for team in all_teams:
            t_id = team["team_id"]
            player_row = all_players.get(t_id)
            
            total_points = 0
            if player_row:
                combined_player_strings = [
                    str(player_row[f"player_{i}"]).lower() for i in range(1, 6)
                ]
                
                for p_str in combined_player_strings:
                    matched_score = 3
                    for rank_keyword, weight in VALORANT_RANK_WEIGHTS.items():
                        if rank_keyword in p_str:
                            matched_score = weight
                            break
                    total_points += matched_score
            
            avg_skill_score = total_points / 5.0
            team_skill_manifest.append({
                "team_id": team["team_id"],
                "team_name": team["team_name"],
                "captain_discord_id": team["captain_discord_id"],
                "skill": avg_skill_score
            })

        team_skill_manifest.sort(key=lambda x: x["skill"], reverse=True)

        bye_team = None
        if len(team_skill_manifest) % 2 != 0:
            lower_half_index = random.randint(len(team_skill_manifest) // 2, len(team_skill_manifest) - 1)
            bye_team = team_skill_manifest.pop(lower_half_index)

        midpoint = len(team_skill_manifest) // 2
        high_seeds = team_skill_manifest[:midpoint]
        low_seeds = team_skill_manifest[midpoint:]

        low_seeds.reverse()
        match_fixtures = []

        for i in range(len(high_seeds)):
            t1 = high_seeds[i]
            t2 = low_seeds[i]

            match_payload = {
                "team_1_id": t1["team_id"],
                "team_2_id": t2["team_id"],
                "match_stage": "ROUND_1",
                "match_status": "SCHEDULED"
            }
            supabase_client.table("matches").insert(match_payload).execute()
            match_fixtures.append((t1, t2))

        # 🎨 DISCORD VISUAL EMBED SETUP
        embed = discord.Embed(
            title="⚔️ TOURNAMENT MATCH FIXTURES GENERATED ⚔️",
            description=f"Operational Mode: **{TOURNAMENT_MODE}**\nTeams have been dynamically balanced and paired based on average roster ranks.",
            color=discord.Color.red()
        )

        for idx, (t1, t2) in enumerate(match_fixtures, 1):
            match_value = f"**Team 1:** `{t1['team_name']}` (Rating: {t1['skill']:.1f}) — <@{t1['captain_discord_id']}>\n" \
                          f"**Team 2:** `{t2['team_name']}` (Rating: {t2['skill']:.1f}) — <@{t2['captain_discord_id']}>"
            embed.add_field(
                name=f"🎮 MATCH {idx} (ROUND 1)",
                value=match_value,
                inline=False
            )

        if bye_team:
            embed.add_field(
                name="✨ BRACKET BYE",
                value=f"`{bye_team['team_name']}` (<@{bye_team['captain_discord_id']}>) received a bye and automatically advances!",
                inline=False
            )

        embed.set_footer(text="Rivaro Gaming Tournament Engine • Open Supabase to view live records.")
        
        await status_msg.delete()
        await message.channel.send(embed=embed)
        return

    # 🛑 ADMIN ROLLBACK COMMAND (Wipes scheduled round 1 scores cleanly)
    if message.content.startswith("!cancel_matches") or message.content.startswith("!cancel_teams"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❌ **Access Denied:** Only tournament administrators can rollback brackets.")
            return

        status_msg = await message.channel.send("🗑️ *Connecting to database matrix to clear match profiles...*")

        try:
            supabase_client.table("matches")\
                .delete()\
                .eq("match_status", "SCHEDULED")\
                .eq("match_stage", "ROUND_1")\
                .execute()

            embed = discord.Embed(
                title="🛑 MATCHMAKING CANCELLED & RESET",
                description="All scheduled **Round 1** match scorecards have been safely deleted from the database ledger.\n\nYou can now re-verify teams and run `!generate_teams` again whenever you are ready.",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Rivaro Gaming Tournament Engine • Database Reset Successful")
            
            await status_msg.delete()
            await message.channel.send(embed=embed)
            
        except Exception as err:
            print(f"Rollback failure: {err}")
            await status_msg.edit(content="❌ *Database rejection: Could not clear active match entries at this time.*")
        return

    # 🛡️ COMMAND: TEAM REGISTRATION TRIGGER
    if message.content.startswith("!register_team"):
        if user_id in REGISTRATION_STATES:
            await message.channel.send("⚠️ You are already running a registration profile interface! Type `!cancel` to drop it.")
            return
            
        REGISTRATION_STATES[user_id] = {
            "step": "AWAITING_TEAM_AND_PHONE",
            "team_name": "",
            "phone_number": ""
        }
        
        await message.channel.send(CUSTOM_GREETING)
        return

    # Cancel Catch Escape Hatch for registration state
    if message.content == "!cancel" and user_id in REGISTRATION_STATES:
        del REGISTRATION_STATES[user_id]
        await message.channel.send("🛑 *Registration process dropped. Session memory cleaned.*")
        return

    # Multiphase Dynamic Interceptor Matrix for Registration Step
    if user_id in REGISTRATION_STATES:
        session = REGISTRATION_STATES[user_id]

        if session["step"] == "AWAITING_TEAM_AND_PHONE":
            raw_input = message.content.strip()
            
            if "," not in raw_input:
                await message.channel.send("⚠️ Please provide both the **Team Name** and **Phone Number** separated by a comma!\n*Example: Team Vandal, 9876543210*")
                return
                
            parts = raw_input.split(",", 1)
            team_name = parts[0].strip()
            phone_num = parts[1].strip()
            
            phone_digits = re.sub(r"\D", "", phone_num)
            
            if len(team_name) < 2:
                await message.channel.send("⚠️ Team name too short! Please provide a valid team name:")
                return
                
            if len(phone_digits) < 8:
                await message.channel.send("⚠️ That doesn't look like a valid phone number. Please check and try again:")
                return
                
            session["team_name"] = team_name
            session["phone_number"] = phone_digits
            session["step"] = "AWAITING_ROSTER_TEXT"
            
            guide_prompt = (
                f"✅ **Team details logged!**\n"
                f"• Team Name: `{team_name}`\n"
                f"• Contact Phone: `{phone_digits}`\n\n"
                f"📝 **Roster Collection Menu:**\n"
                f"Please type out your **5 players** with their **Riot ID** and **Rank** on separate lines. "
                f"Example layout format:\n"
                f"```text\n"
                f"1. ViperBait#4411 - Platinum 1\n"
                f"2. SpikeRunner#9988 - Diamond 3\n"
                f"3. JettDiff#0022 - Silver 2\n"
                f"4. NeonMain#5544 - Immortal 2\n"
                f"5. ReynaClutch#1122 - Gold 3\n"
                f"```"
            )
            await message.channel.send(guide_prompt)
            return

        if session["step"] == "AWAITING_ROSTER_TEXT":
            await message.channel.send("⏳ *Processing and verifying your roster list...*")
            
            try:
                parsed_roster = parse_text_roster_list(message.content)
            except Exception as ai_error:
                print(f"CRITICAL AI FAILURE: {ai_error}")
                await message.channel.send("❌ *Registration could not be completed due to a processing timeout. Please try again in a moment.*")
                del REGISTRATION_STATES[user_id]
                return
            
            if parsed_roster.is_valid:
                try:
                    commit_simplified_team_to_db(user_id, session["team_name"], session["phone_number"], parsed_roster.players)
                    
                    if TOURNAMENT_MODE == "FREE":
                        mode_note = "✨ *Free entry mode active: Your team is instantly verified and cleared for matchmaking!*"
                    else:
                        mode_note = "⌛ *Paid entry mode active: Your registration is pending. Brackets will lock once payment is approved by staff.*"
                        
                    await message.channel.send(
                        f"🎉 **Registration Successful!**\n"
                        f"🛡️ Team **'{session['team_name']}'** has been successfully cataloged.\n"
                        f"{mode_note}"
                    )
                except Exception as db_error:
                    err_str = str(db_error)
                    if "23505" in err_str or "teams_team_name_key" in err_str:
                        await message.channel.send(f"⚠️ **Registration Failed:** The team name `{session['team_name']}` is already registered!")
                    else:
                        await message.channel.send("❌ *Registration could not be completed. Please contact an Administrator.*")
                    print(f"Database insertion exception: {db_error}")
                finally:
                    del REGISTRATION_STATES[user_id]
            else:
                await message.channel.send(
                    f"⚠️ **Roster Verification Failed:** {parsed_roster.error_message}\n"
                    f"Please re-enter your 5-player list following the correct structure:"
                )


# =====================================================================
# RENDER PORTS COMPLIANCE BACKEND DUMMY DAEMON
# =====================================================================
def run_dummy_server():
    """Spins up a lightweight background web server to pass Render web traffic port scans."""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    discord_gateway_client.run(DISCORD_TOKEN)