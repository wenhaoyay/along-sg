"""Offline fixed-catalog benchmark; never claims live or human relevance scores."""
import asyncio
import hashlib
import gc
import json
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import ScoringWeights
from app.db import HubRepository
from app.domain import Coordinate
from app.providers.mock import MockOneMapProvider
from app.services.optimizer import Optimizer

CASES = (
    ('northeast-orchard', (1.4052, 103.9024), (1.3043, 103.8322)),
    ('west-city', (1.3331, 103.7422), (1.2830, 103.8513)),
    ('east-orchard', (1.3530, 103.9451), (1.3043, 103.8322)),
)


async def run():
    rows = []
    with tempfile.TemporaryDirectory(prefix='along-benchmark-') as directory:
        repo = HubRepository(Path(directory) / 'fixed.db'); repo.initialize()
        catalog = json.dumps([asdict(hub) for hub in repo.find_for_categories(repo.category_catalog())], sort_keys=True, default=str)
        for case_id, origin, destination in CASES:
            for errands in [('groceries',), ('groceries', 'pharmacy')]:
                optimizer = Optimizer(MockOneMapProvider(), repo, ScoringWeights(),
                    max_candidates=6, max_straight_line_detour_km=20, routing_soft_budget=12, routing_hard_budget=18)
                baseline, recommendations, diagnostics = await optimizer.optimize(Coordinate(*origin), Coordinate(*destination),
                    list(errands), datetime.fromisoformat('2026-09-08T10:00:00+08:00'))
                best = recommendations.get('best_overall')
                rows.append({'id': case_id + '-' + '-'.join(errands), 'origin': origin, 'destination': destination,
                    'errands': errands, 'baseline_minutes': baseline.duration_minutes,
                    'outcome': 'recommendation' if best else 'no_result',
                    'stops': [hub.name for hub in best.ordered_stops] if best else [],
                    'total_minutes': best.total_route.duration_minutes if best else None,
                    'detour_minutes': best.incremental_detour_minutes if best else None,
                    'walking_m': best.total_route.walking_distance_m if best else None,
                    'transfers': best.total_route.transfers if best else None,
                    'diagnostics': diagnostics, 'human_review': None})
        # SQLite context managers end transactions but do not close connections.
        # Release unreachable connections before Windows removes the temp DB.
        gc.collect()
    return {'schema_version': 1, 'mode': 'mock', 'live_verified': False, 'human_reviewed': False,
            'catalog_sha256': hashlib.sha256(catalog.encode()).hexdigest(),
            'weights': asdict(ScoringWeights()), 'cases': rows}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(run()), indent=2, default=str))
