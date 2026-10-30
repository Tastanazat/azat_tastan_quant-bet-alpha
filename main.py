from src.engine import QuantBettingEngine, TeamMetrics
from src.fetcher import fetch_club_elo, fetch_understat_metrics
from src.notifier import send_telegram_alert

def run_pipeline():
    print("QuantBet Alpha: Canlı Veri Akışı ve Analiz Başlatılıyor...")
    engine = QuantBettingEngine(league_avg_xg=1.38)
    
    # 1. Takım Adları Tanımlanır
    home_team = "Galatasaray"
    away_team = "Fenerbahce"
    
    # 2. Canlı Veriler Otomatik Çekilir (Elo + Understat npxG/PPDA + EWMA)
    home_stats = fetch_understat_metrics(home_team)
    away_stats = fetch_understat_metrics(away_team)
    
    ev_sahibi = TeamMetrics(
        name=home_team, 
        elo=fetch_club_elo(home_team), 
        npxg_for=home_stats["npxg_for"], 
        npxg_against=home_stats["npxg_against"], 
        ppda=home_stats["ppda"], 
        rest_days=6
    )
    
    deplasman = TeamMetrics(
        name=away_team, 
        elo=fetch_club_elo(away_team), 
        npxg_for=away_stats["npxg_for"], 
        npxg_against=away_stats["npxg_against"], 
        ppda=away_stats["ppda"], 
        rest_days=5
    )
    
    # Örnek Piyasadan Çekilen Oranlar
    oranlar = {"MS 1": 2.05, "MS X": 3.40, "MS 2": 3.50, "2.5 Üst": 1.80}

    # 3. Dixon-Coles & Poisson Matris Hesaplaması
    lam_h, lam_a = engine.calculate_lambdas(ev_sahibi, deplasman)
    matrix = engine.build_score_matrix(lam_h, lam_a)
    probs = engine.extract_probabilities(matrix)

    # 4. Raporlama ve Telegram Bildirimi
    report = [
        "🤖 *QuantBet Alpha - Otomatik Kantitatif Rapor*",
        f"⚽ *{ev_sahibi.name} (Elo: {ev_sahibi.elo}) vs {deplasman.name} (Elo: {deplasman.elo})*",
        f"📊 *EWMA npxG* -> Ev: `{lam_h}` | Dep: `{lam_a}`",
        f"🔬 *Pres (PPDA)* -> Ev: `{ev_sahibi.ppda}` | Dep: `{deplasman.ppda}`\n" + "-"*30
    ]

    found = False
    for market, odd in oranlar.items():
        res = engine.evaluate_bet(probs[market], odd, kelly_fraction=0.25, min_ev=0.03)
        if res['signal'] == "YATIRIM UYGUN (+EV)":
            found = True
            report.append(
                f"✅ **{market}**\n"
                f"• Model Olasılık: `%{res['model_prob_pct']}` (Adil: `{res['fair_odd']}`)\n"
                f"• Büro Oranı: `{res['bookie_odd']}`\n"
                f"• Beklenen Değer (EV): `+% {res['ev_pct']}`\n"
                f"• Çeyrek Kelly Kasa: `%{res['quarter_kelly_pct']}`\n"
            )

    if not found:
        report.append("⚠️ Model filtresini geçen (%3+ EV) fırsat bulunamadı.")

    send_telegram_alert("\n".join(report))
    print("Analiz tamamlandı ve Telegram'a gönderildi.")

if __name__ == "__main__":
    run_pipeline()
