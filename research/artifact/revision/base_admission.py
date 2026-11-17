



from dataclasses import dataclass
from itertools import combinations
import random
import networkx as nx


@dataclass
class Request:
    ids: tuple
    updates: tuple
    lookups: tuple
    terms: tuple
    scan: int


def subsets(items):
    return (
        frozenset(xs) for n in range(len(items) + 1) for xs in combinations(items, n)
    )


def serve(req, facilities):
    if "base" not in facilities:
        return req.scan
    eligible = [j for j, key in enumerate(req.ids) if key in facilities]
    return min(
        req.scan,
        min(
            sum(a for consumers, a in req.terms if not consumers <= used)
            + sum(
                req.lookups[j] if j in used else req.updates[j]
                for j in range(len(req.ids))
            )
            for used in subsets(eligible)
        ),
    )


def closure(reqs, prices):
    graph = nx.DiGraph()
    source = "source"
    sink = "sink"
    graph.add_nodes_from([source, sink])
    weights = {k: -v for k, v in prices.items()}
    implications = [(k, "base") for k in prices if k != "base"]
    for i, r in enumerate(reqs):
        z = ("indexed", i)
        tree = sum(r.updates) + sum(a for _, a in r.terms)
        weights[z] = r.scan - tree
        implications.append((z, "base"))
        for j, k in enumerate(r.ids):
            output = ("cache", i, j)
            weights[output] = r.updates[j] - r.lookups[j]
            implications.extend([(output, z), (output, k)])
        for m, (consumers, a) in enumerate(r.terms):
            reward = ("saved", i, m)
            weights[reward] = a
            implications.extend((reward, ("cache", i, j)) for j in consumers)
    cap = 1 + sum(max(0, w) for w in weights.values())
    for v, w in weights.items():
        graph.add_node(v)
        if w > 0:
            graph.add_edge(source, v, capacity=w)
        if w < 0:
            graph.add_edge(v, sink, capacity=-w)
    for u, v in implications:
        graph.add_edge(u, v, capacity=cap)
    residual = nx.algorithms.flow.preflow_push(graph, source, sink)
    usable = nx.DiGraph()
    usable.add_nodes_from(graph)
    usable.add_edges_from(
        (u, v) for u, v, e in residual.edges(data=True) if e["flow"] < e["capacity"]
    )

    chosen = set(prices) - nx.ancestors(usable, sink)
    gain = cap - 1 - residual.graph["flow_value"]
    return chosen, sum(r.scan for r in reqs) - gain


def check():
    rng = random.Random(23863)
    prefixes = 0
    transitions = 0
    maxratio = 0.0
    for _ in range(24):
        prices = {
            "base": rng.randint(10, 80),
            **{q: rng.randint(0, 14) for q in range(5)},
        }
        options = [frozenset()] + [u | {"base"} for u in subsets(range(5))]
        hist = []
        prior = set()
        served = 0
        for t in range(10):
            width = rng.randint(1, 4)
            req = Request(
                tuple(rng.choices(range(5), k=width)),
                tuple(rng.randint(0, 4) for _ in range(width)),
                tuple(rng.randint(0, 4) for _ in range(width)),
                tuple(
                    (
                        frozenset(rng.sample(range(width), rng.randint(1, width))),
                        rng.randint(1, 11),
                    )
                    for _ in range(4)
                ),
                rng.randint(1, 35),
            )
            hist.append(req)
            active, opt = closure(hist, prices)
            values = [
                sum(prices[k] for k in c) + sum(serve(r, c) for r in hist)
                for c in options
            ]
            best = min(values)
            maximal = set().union(*(c for c, v in zip(options, values) if v == best))
            assert opt == best and active == maximal and prior <= active
            if "base" in active - prior:
                transitions += 1
            served += serve(req, active)
            paid = served + sum(prices[k] for k in active)
            assert paid <= 2 * opt
            maxratio = max(maxratio, paid / opt)
            prefixes += 1
            prior = active
    print(
        "verified prefixes",
        prefixes,
        "base activations",
        transitions,
        "max ratio",
        round(maxratio, 4),
    )


if __name__ == "__main__":
    check()
