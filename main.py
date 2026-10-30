from src.engine import QuantBettingEngine, TeamMetrics
from src.fetcher import fetch_club_elo
from src.notifier import send_telegram_alert

def run_pipeline():
    engine = QuantBettingEngine(league_avg_xg=1.35)
    
    # Örnek maç verisi (Gerçek sistemde fetcher ile maç listesi döngüye sokulur)
    ev_sahibi = TeamMetrics(name="Galatasaray", elo=fetch_club_elo("Galatasaray"), npxg_for=1.75, npxg_against=0.90, ppda=8.5, rest_days=6)
    deplasman = TeamMetrics(name="Fenerbahce", elo=fetch_club_elo("Fenerbahce"), npxg_for=1.70, npxg_against=0.95, ppda=9.0, rest_days=5)
    
    oranlar = {"MS 1": 2.05, "MS X": 3.40, "MS 2": 3.50, "2.5 Üst": 1.80}

    lam_h, lam_a = engine.calculate_lambdas(ev_sahibi, deplasman)
    matrix = engine.build_score_matrix(lam_h, lam_a)
    probs = engine.extract_probabilities(matrix)

    report = [
        "🤖 *QuantBet Alpha - Otomatik Rapor*",
        f"⚽ *{ev_sahibi.name} (Elo: {ev_sahibi.elo}) vs {deplasman.name} (Elo: {deplasman.elo})*",
        f"📊 xG -> Ev: `{lam_h}` | Dep: `{lam_a}`\n" + "-"*30
    ]

    found = False
    for market, odd in oranlar.items():
        res = engine.evaluate_bet(probs[market], odd, kelly_fraction=0.25, min_ev=0.03)
        if res['signal'] == "YATIRIM UYGUN (+EV)":
            found = True
            report.append(
                f"✅ **{market}**\n"
                f"• Model: `%{res['model_prob_pct']}` (Adil: `{res['fair_odd']}`)\n"
                f"• Büro Oranı: `{res['bookie_odd']}`\n"
                f"• Beklenen Değer: `+% {res['ev_pct']}`\n"
                f"• Çeyrek Kelly: `%{res['quarter_kelly_pct']}`\n"
            )

    if not found:
        report.append("⚠️ Kriterleri sağlayan +EV fırsatı bulunamadı.")

    send_telegram_alert("\n".join(report))

if __name__ == "__main__":
    run_pipeline()

