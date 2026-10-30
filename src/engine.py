
import math
import numpy as np
from dataclasses import dataclass
from typing import Dict, Tuple

@dataclass
class TeamMetrics:
    name: str
    elo: float
    npxg_for: float
    npxg_against: float
    ppda: float
    rest_days: int

class QuantBettingEngine:
    def __init__(self, league_avg_xg: float = 1.35, home_adv_elo: float = 65.0, rho: float = -0.11):
        self.league_avg = league_avg_xg
        self.home_adv = home_adv_elo
        self.rho = rho
        self.max_goals = 10

    def calculate_lambdas(self, home: TeamMetrics, away: TeamMetrics) -> Tuple[float, float]:
        home_att = home.npxg_for / self.league_avg
        home_def = home.npxg_against / self.league_avg
        away_att = away.npxg_for / self.league_avg
        away_def = away.npxg_against / self.league_avg

        base_lambda_h = home_att * away_def * self.league_avg
        base_lambda_a = away_att * home_def * self.league_avg

        elo_diff = (home.elo + self.home_adv) - away.elo
        elo_factor_h = 1 + (elo_diff / 1400.0)
        elo_factor_a = 1 - (elo_diff / 1400.0)

        fatigue_h = 0.94 if home.rest_days < 3 else 1.0
        fatigue_a = 0.94 if away.rest_days < 3 else 1.0

        lambda_h = max(0.25, base_lambda_h * elo_factor_h * fatigue_h)
        lambda_a = max(0.25, base_lambda_a * elo_factor_a * fatigue_a)

        return round(lambda_h, 3), round(lambda_a, 3)

    @staticmethod
    def _poisson_pmf(k: int, lam: float) -> float:
        return (lam ** k) * math.exp(-lam) / math.factorial(k)

    def _dixon_coles_tau(self, x: int, y: int, lam_h: float, lam_a: float) -> float:
        if x == 0 and y == 0:
            return 1.0 - (lam_h * lam_a * self.rho)
        elif x == 0 and y == 1:
            return 1.0 + (lam_h * self.rho)
        elif x == 1 and y == 0:
            return 1.0 + (lam_a * self.rho)
        elif x == 1 and y == 1:
            return 1.0 - self.rho
        return 1.0

    def build_score_matrix(self, lam_h: float, lam_a: float) -> np.ndarray:
        matrix = np.zeros((self.max_goals, self.max_goals))
        for i in range(self.max_goals):
            for j in range(self.max_goals):
                p_h = self._poisson_pmf(i, lam_h)
                p_a = self._poisson_pmf(j, lam_a)
                tau = self._dixon_coles_tau(i, j, lam_h, lam_a)
                matrix[i, j] = p_h * p_a * tau
        return matrix / np.sum(matrix)

    def extract_probabilities(self, matrix: np.ndarray) -> Dict[str, float]:
        prob_home = float(np.sum(np.tril(matrix, -1)))
        prob_draw = float(np.sum(np.diag(matrix)))
        prob_away = float(np.sum(np.triu(matrix, 1)))

        prob_under_25 = 0.0
        for i in range(self.max_goals):
            for j in range(self.max_goals):
                if i + j <= 2:
                    prob_under_25 += matrix[i, j]

        return {
            "MS 1": prob_home,
            "MS X": prob_draw,
            "MS 2": prob_away,
            "2.5 Üst": 1.0 - prob_under_25,
            "2.5 Alt": prob_under_25
        }

    @staticmethod
    def evaluate_bet(model_prob: float, bookie_odd: float, kelly_fraction: float = 0.25, min_ev: float = 0.03) -> Dict:
        ev = (model_prob * bookie_odd) - 1.0
        fair_odd = round(1.0 / model_prob, 2) if model_prob > 0 else 99.0
        
        if ev >= min_ev and bookie_odd > 1.0:
            full_kelly = ev / (bookie_odd - 1.0)
            stake_pct = round(full_kelly * kelly_fraction * 100, 2)
            signal = "YATIRIM UYGUN (+EV)"
        else:
            stake_pct = 0.0
            signal = "PAS GEÇ"

        return {
            "model_prob_pct": round(model_prob * 100, 2),
            "fair_odd": fair_odd,
            "bookie_odd": bookie_odd,
            "ev_pct": round(ev * 100, 2),
            "quarter_kelly_pct": stake_pct,
            "signal": signal
        }
