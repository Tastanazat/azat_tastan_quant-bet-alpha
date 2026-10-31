import os
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from io import StringIO
from src.engine import QuantBettingEngine, TeamMetrics
from src.fetcher import fetch_understat_metrics, fetch_odds_from_api
from src.notifier import send_telegram_alert

def clean_team_name(team_name: str) -> str:
    tr_chars = {'ç': 'c', 'ğ': 'g', 'ö': 'o', 'ş': 's', 'ü': 'u', 'İ': 'I', 'ı': 'i'}
    for k, v in tr_chars.items():
        team_name = team_name.replace(k, v)
    return team_name.strip()

def fetch_club_elo(team_name: str) -> float:
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

def evaluate_value_bet(model_prob: float, bookie_odd: float, min_model_prob: float = 0.20, min_ev: float = 0.02) -> dict:
    """
    SÜRPRİZ VE DEĞER ODAKLI FİLTRE (Oran Sınırı Yok):
    - model_prob: En az %20 olasılık (Çok düşük ihtimalli absürt sürprizleri eler, gerçekçi ihtimal arar).
    - bookie_odd: Üst oran sınırı YOK! Herhangi bir oran olabilir.
    - min_ev: En az %2 Beklenen Değer (+EV) avantajı.
    """
    ev = (model_prob * bookie_odd) - 1.0
    fair_odd = round(1.0 / model_prob, 2) if model_prob > 0 else 99.0
    
    if model_prob >= min_model_prob and ev >= min_ev and bookie_odd > 1.0:
        full_kelly = ev / (bookie_odd - 1.0)
        # Sürpriz maçlarda varyans yüksek olduğu için Çeyrek Kelly'yi (0.25) biraz daha güvenli tutuyoruz
        stake_pct = round(full_kelly * 0.20 * 100, 2) 
        signal = "DEĞERLİ / SÜRPRİZ +EV"
    else:
        stake_pct = 0.0
        signal = "PAS"

    return {
        "model_prob_pct": round(model_prob * 100, 2),
        "fair_odd": fair_odd,
        "bookie_odd": bookie_odd,
        "ev_pct": round(ev * 100, 2),
        "quarter_kelly_pct": stake_pct,
        "signal": signal
    }

def run_pipeline():
    print("QuantBet Alpha: Oran Sınırı Olmayan Değer / Sürpriz Taraması Başlatılıyor...")
    send_telegram_alert("🤖 *QuantBet Alpha* sürpriz ve değer avcılığı modu aktif (Oran sınırı kaldırıldı, %20+ olasılık).")
    
    european_leagues = [
        "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", 
        "soccer_germany_bundesliga", "soccer_france_ligue_one", "soccer_turkey_super_lig"
    ]
    
    engine = QuantBettingEngine(league_avg_xg=1.35)
    scanned_count = 0
    found_any_value = False

    now_utc = datetime.now(timezone.utc)
    target_window = now_utc + timedelta(hours=48)

    for league_key in european_leagues:
        fixtures = fetch_odds_from_api(sport_key=league_key)
        if not fixtures:
            continue

        for game in fixtures:
            commence_time_str = game.get('commence_time')
            if not commence_time_str:
                continue
            
            game_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
            if not (now_utc <= game_time <= target_window):
                continue 

            scanned_count += 1
            home_team = game.get('home_team')
            away_team = game.get('away_team')
            bookmakers = game.get('bookmakers', [])
            
            if not bookmakers:
                continue
                
            markets = bookmakers[0].get('markets', [])
            odds_dict = {}
            for market in markets:
                # 1X2 ve 2.5 Alt/Üst tüm pazarları dahil ediyoruz
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
                        if outcome.get('point') == 2.5:
                            if outcome['name'] == 'Over':
                                odds_dict['2.5 Üst'] = outcome['price']
                            elif outcome['name'] == 'Under':
                                odds_dict['2.5 Alt'] = outcome['price']

            if not odds_dict:
                continue

            home_elo = fetch_club_elo(home_team)
            away_elo = fetch_club_elo(away_team)
            
            home_stats = fetch_understat_metrics(home_team)
            away_stats = fetch_understat_metrics(away_team)
            
            ev_sahibi = TeamMetrics(name=home_team, elo=home_elo, npxg_for=home_stats["npxg_for"], npxg_against=home_stats["npxg_against"], ppda=home_stats["ppda"], rest_days=5)
            deplasman = TeamMetrics(name=away_team, elo=away_elo, npxg_for=away_stats["npxg_for"], npxg_against=away_stats["npxg_against"], ppda=away_stats["ppda"], rest_days=5)

            lam_h, lam_a = engine.calculate_lambdas(ev_sahibi, deplasman)
            matrix = engine.build_score_matrix(lam_h, lam_a)
            probs = engine.extract_probabilities(matrix)

            local_game_time = game_time + timedelta(hours=3)
            time_formatted = local_game_time.strftime('%d.%m.%Y - %H:%M')

            report = [
                f"🎯 *QuantBet Alpha (Değer & Sürpriz Raporu)*",
                f"⏰ *Başlama (TSİ):* `{time_formatted}`",
                f"🌍 *Lig:* `{league_key.replace('soccer_', '').upper()}`",
                f"⚽ *{ev_sahibi.name} vs {deplasman.name}*",
                f"📊 *xG* -> Ev: `{lam_h}` | Dep: `{lam_a}`\n" + "-"*30
            ]

            found_value = False
            for market, odd in odds_dict.items():
                if market in probs:
                    # %20+ olasılık, üst oran sınırı yok, +%2 EV
                    res = evaluate_value_bet(probs[market], odd, min_model_prob=0.20, min_ev=0.02)
                    if res['signal'] == "DEĞERLİ / SÜRPRİZ +EV":
                        found_value = True
                        found_any_value = True
                        report.append(
                            f"🔥 **DEĞER TESPİTİ: {market}**\n"
                            f"• Model Olasılık: `%{res['model_prob_pct']}` (Adil Oran: `{res['fair_odd']}`)\n"
                            f"• Büro Oranı: `{res['bookie_odd']}`\n"
                            f"• Beklenen Değer (EV): `+% {res['ev_pct']}`\n"
                            f"• Önerilen Kasa: `%{res['quarter_kelly_pct']}`\n"
                        )

            if found_value:
                send_telegram_alert("\n".join(report))

    summary_msg = f"🏁 Sürpriz taraması tamamlandı. İncelenen toplam maç: {scanned_count}"
    print(summary_msg)
    send_telegram_alert(summary_msg)

if __name__ == "__main__":
    run_pipeline()
