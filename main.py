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

    # 2. Map and Insert Player Records with a numeric placeholder string
    player_payloads = []
    for player in roster_list:
        player_payloads.append({
            "team_id": inserted_team_id,
            "player_discord_id": "000000000000000000",  # 💡 UPDATED TO NUMERIC FORMAT
            "riot_id": player.riot_id,
            "rank": player.rank
        })
        
    if player_payloads:
        supabase_client.table("players").insert(player_payloads).execute()
        
    return True