import os
import requests
import pandas as pd
from io import StringIO
from src.engine import QuantBettingEngine, TeamMetrics
from src.fetcher import fetch_understat_metrics, fetch_odds_from_api
from src.notifier import send_telegram_alert

def clean_team_name(team_name: str) -> str:
    """ClubElo ve Understat uyumluluğu için Türkçe karakterleri temizler ve boşlukları kaldırır."""
    tr_chars = {'ç': 'c', 'ç': 'c', 'ğ': 'g', 'ö': 'o', 'ş': 's', 'ü': 'u', 'İ': 'I', 'ı': 'i'}
    for k, v in tr_chars.items():
        team_name = team_name.replace(k, v)
    return team_name.strip()

def fetch_club_elo(team_name: str) -> float:
    """ClubElo API üzerinden takımın güncel Elo puanını dinamik ve temizlenmiş isimle çeker."""
    try:
        formatted_name = clean_team_name(team_name).replace(" ", "")
        url = f"http://api.clubelo.com/{formatted_name}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            df = pd.read_csv(StringIO(res.text))
            if not df.empty:
                return float(df.iloc[-1]['Elo'])
    except Exception as e:
        print(f"Elo çekilemedi ({team_name}): {e}")
    return 1500.0 # Bağlantı hatası durumunda varsayılan güvenli lig ortalaması

def run_pipeline():
    print("QuantBet Alpha: Canlı Fikstür Taraması ve Analiz Başlatılıyor...")
    engine = QuantBettingEngine(league_avg_xg=1.38)
    
    # 1. The Odds API üzerinden güncel maç fikstürünü çekiyoruz
    fixtures = fetch_odds_from_api(sport_key="soccer_turkey_super_lig")
    
    if not fixtures:
        print("Bugün için API'den maç çekilemedi veya maç bulunamadı.")
        return

    for game in fixtures:
        home_team = game.get('home_team')
        away_team = game.get('away_team')
        bookmakers = game.get('bookmakers', [])
        
        if not bookmakers:
            continue
            
        # Büronun (Pinnacle/Bookie) maç sonu ve alt/üst oranlarını alıyoruz
        markets = bookmakers[0].get('markets', [])
        odds_dict = {}
        for market in markets:
            if market['key'] == 'h2h':
                for outcome in market['outcomes']:
                    if outcome['name'] == home_team:
                        odds_dict['MS 1'] = outcome['price']
                    elif outcome['name'] == away_team:
                        odds_dict['MS 2'] = outcome['price']
                    elif outcome['name'] == 'Draw':
                        odds_dict['MS X'] = outcome['price']
            elif market['key'] == 'totals':
                for outcome in market['outcomes']:
                    if outcome['name'] == 'Over' and outcome.get('point') == 2.5:
                        odds_dict['2.5 Üst'] = outcome['price']

        if len(odds_dict) < 3:
            continue

        # 2. Canlı Elo ve Understat EWMA Verilerini Çek
        home_elo = fetch_club_elo(home_team)
        away_elo = fetch_club_elo(away_team)
        
        home_stats = fetch_understat_metrics(home_team)
        away_stats = fetch_understat_metrics(away_team)
        
        ev_sahibi = TeamMetrics(
            name=home_team, 
            elo=home_elo, 
            npxg_for=home_stats["npxg_for"], 
            npxg_against=home_stats["npxg_against"], 
            ppda=home_stats["ppda"], 
            rest_days=5
        )
        deplasman = TeamMetrics(
            name=away_team, 
            elo=away_elo, 
            npxg_for=away_stats["npxg_for"], 
            npxg_against=away_stats["npxg_against"], 
            ppda=away_stats["ppda"], 
            rest_days=5
        )

        # 3. Model Hesaplaması (Dixon-Coles + Poisson Matrisi)
        lam_h, lam_a = engine.calculate_lambdas(ev_sahibi, deplasman)
        matrix = engine.build_score_matrix(lam_h, lam_a)
        probs = engine.extract_probabilities(matrix)

        # 4. Rapor Oluşturma ve +EV Filtrelemesi (%3+)
        report = [
            "🤖 *QuantBet Alpha - Canlı Maç Raporu*",
            f"⚽ *{ev_sahibi.name} (Elo: {ev_sahibi.elo}) vs {deplasman.name} (Elo: {deplasman.elo})*",
            f"📊 *EWMA npxG* -> Ev: `{lam_h}` | Dep: `{lam_a}`\n" + "-"*30
        ]

        found_value = False
        for market, odd in odds_dict.items():
            if market in probs:
                res = engine.evaluate_bet(probs[market], odd, kelly_fraction=0.25, min_ev=0.03)
                if res['signal'] == "YATIRIM UYGUN (+EV)":
                    found_value = True
                    report.append(
                        f"✅ **{market}**\n"
                        f"• Model Olasılık: `%{res['model_prob_pct']}` (Adil: `{res['fair_odd']}`)\n"
                        f"• Büro Oranı: `{res['bookie_odd']}`\n"
                        f"• Beklenen Değer (EV): `+% {res['ev_pct']}`\n"
                        f"• Çeyrek Kelly Kasa: `%{res['quarter_kelly_pct']}`\n"
                    )

        # Sadece +EV fırsatı barındıran maçlar Telegram'a gönderilir
        if found_value:
            send_telegram_alert("\n".join(report))
            print(f"Rapor gönderildi: {home_team} vs {away_team}")
        else:
            print(f"Fırsat bulunamadı (Pas): {home_team} vs {away_team}")

if __name__ == "__main__":
    run_pipeline()
