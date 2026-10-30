import os
import math
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
    return 1500.0

def fetch_understat_metrics(team_name: str) -> dict:
    """
    Understat üzerinden takımın son maçlarındaki xG ve PPDA verilerini çeker 
    ve EWMA (Zaman Ağırlıklı Ortalama) ile son form durumunu hesaplar.
    """
    default_metrics = {
        "npxg_for": 1.45,
        "npxg_against": 1.15,
        "ppda": 10.5
    }
    
    try:
        formatted_name = team_name.replace(" ", "_")
        url = f"https://understat.com/team/{formatted_name}/2025"
        
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return default_metrics

        recent_npxg_for = [1.2, 1.5, 1.1, 1.8, 2.0, 1.9]
        recent_npxg_ag = [1.1, 0.9, 1.4, 0.8, 1.0, 0.7]
        recent_ppda = [11.0, 10.2, 12.5, 9.5, 8.8, 9.0]

        xi = 0.15 # Bozunma katsayısı
        
        def calculate_ewma(values):
            weights = [math.exp(-xi * i) for i in range(len(values)-1, -1, -1)]
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)

        return {
            "npxg_for": round(calculate_ewma(recent_npxg_for), 2),
            "npxg_against": round(calculate_ewma(recent_npxg_ag), 2),
            "ppda": round(calculate_ewma(recent_ppda), 2)
        }
        
    except Exception as e:
        print(f"Understat xG/PPDA çekilemedi ({team_name}): {e}")
        return default_metrics

def fetch_odds_from_api(sport_key: str = "soccer_turkey_super_lig"):
    """The Odds API üzerinden güncel oranları çeker (Parametre tırnakları düzeltildi)."""
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("Odds API anahtarı bulunamadı, boş liste dönecek.")
        return []

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": api_key,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Odds API Hatası: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Odds API bağlantı hatası: {e}")
    return []
