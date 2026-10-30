
import os
import requests
import pandas as pd
from io import StringIO

def fetch_club_elo(team_name: str) -> float:
    """ClubElo API üzerinden takımın güncel Elo puanını çeker."""
    try:
        url = f"http://api.clubelo.com/{team_name.replace(' ', '')}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            df = pd.read_csv(StringIO(res.text))
            if not df.empty:
                return float(df.iloc[-1]['Elo'])
    except Exception as e:
        print(f"Elo çekilemedi ({team_name}): {e}")
    return 1500.0 # Varsayılan ortalama güç

def fetch_odds_from_api(sport_key: str = "soccer_turkey_super_lig"):
    """The Odds API üzerinden güncel oranları çeker."""
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("Odds API anahtarı bulunamadı, mock veri kullanılacak.")
        return []

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": api_key,
        regions: "eu",
        markets: "h2h,totals",
        oddsFormat: "decimal"
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    return []
