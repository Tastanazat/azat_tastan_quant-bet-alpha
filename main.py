import os
import requests
import pandas as pd
from io import StringIO
from src.engine import QuantBettingEngine, TeamMetrics
from src.fetcher import fetch_understat_metrics, fetch_odds_from_api
from src.notifier import send_telegram_alert

def clean_team_name(team_name: str) -> str:
    """ClubElo ve Understat uyumluluğu için Türkçe karakterleri temizler ve boşlukları kaldırır."""
    tr_chars = {'ç': 'c', 'ğ': 'g', 'ö': 'o', 'ş': 's', 'ü': 'u', 'İ': 'I', 'ı': 'i'}
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
    return 1500.0

def run_pipeline():
    print("QuantBet Alpha: Tüm Avrupa Ligleri Fikstür Taraması Başlatılıyor...")
    
    # 🌍 Taranacak Majör Avrupa Ligleri ve Türkiye Listesi
    european_leagues = [
        "soccer_epl",                  # İngiltere Premier Lig
        "soccer_spain_la_liga",        # İspanya La Liga
        "soccer_italy_serie_a",        # İtalya Serie A
        "soccer_germany_bundesliga",   # Almanya Bundesliga
        "soccer_france_ligue_one",     # Fransa Ligue 1
        "soccer_turkey_super_lig"      # Türkiye Süper Lig
    ]
    
    engine = QuantBettingEngine(league_avg_xg=1.35)
    total_scanned = 0
    found_any_value = False

    # Ligleri sırayla dönüyoruz
    for league_key in european_leagues:
        print(f"Taranıyor -> {league_key}")
        fixtures = fetch_odds_from_api(sport_key=league_key)
        
        if not fixtures:
            continue

        for game in fixtures:
            total_scanned += 1
            home_team = game.get('home_team')
            away_team = game.get('away_team')
            bookmakers = game.get('bookmakers', [])
            
            if not bookmakers:
                continue
                
            # Maç sonu (1X2) ve Alt/Üst oranlarını alıyoruz
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

            # Canlı Elo ve Understat EWMA Verileri
            home_elo = fetch_club_elo(home_team)
            away_elo = fetch_club_elo(away_team)
            
            home_stats = fetch_understat_metrics(home_team)
            away_stats = fetch_understat_metrics(away_team)
            
            ev_sahibi = TeamMetrics(
                name=home_team, elo=home_elo, 
                npxg_for=home_stats["npxg_for"], npxg_against=home_stats["npxg_against"], 
                ppda=home_stats["ppda"], rest_days=5
            )
            deplasman = TeamMetrics(
                name=away_team, elo=away_elo, 
                npxg_for=away_stats["npxg_for"], npxg_against=away_stats["npxg_against"], 
                ppda=away_stats["ppda"], rest_days=5
            )

            # Dixon-Coles + Poisson Matris Hesaplaması
            lam_h, lam_a = engine.calculate_lambdas(ev_sahibi, deplasman)
            matrix = engine.build_score_matrix(lam_h, lam_a)
            probs = engine.extract_probabilities(matrix)

            # Rapor Hazırlığı
            report = [
                f"🌍 *QuantBet Alpha ({league_key.replace('soccer_', '').upper()})*",
                f"⚽ *{ev_sahibi.name} (Elo: {ev_sahibi.elo}) vs {deplasman.name} (Elo: {deplasman.elo})*",
                f"📊 *EWMA npxG* -> Ev: `{lam_h}` | Dep: `{lam_a}`\n" + "-"*30
            ]

            found_value = False
            for market, odd in odds_dict.items():
                if market in probs:
                    res = engine.evaluate_bet(probs[market], odd, kelly_fraction=0.25, min_ev=0.03)
                    if res['signal'] == "YATIRIM UYGUN (+EV)":
                        found_value = True
                        found_any_value = True
                        report.append(
                            f"✅ **{market}**\n"
                            f"• Model Olasılık: `%{res['model_prob_pct']}` (Adil: `{res['fair_odd']}`)\n"
                            f"• Büro Oranı: `{res['bookie_odd']}`\n"
                            f"• Beklenen Değer (EV): `+% {res['ev_pct']}`\n"
                            f"• Çeyrek Kelly Kasa: `%{res['quarter_kelly_pct']}`\n"
                        )

            # Sadece değerli bahisleri Telegram'a basar
            if found_value:
                send_telegram_alert("\n".join(report))

    print(f"Tarama tamamlandı. Toplam incelenen maç: {total_scanned}")
    if not found_any_value:
        print("Taranan Avrupa liglerinde bugün %3+ EV fırsatı bulunamadı.")

if __name__ == "__main__":
    run_pipeline()
