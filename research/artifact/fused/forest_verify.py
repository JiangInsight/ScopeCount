

from itertools import combinations, product
import random


def acyclic(g, s, edges):
    parent = list(range(g + s))

    def root(i):
        while i != parent[i]:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in edges:
        a = root(i)
        b = root(g + j)
        if a == b:
            return False
        parent[a] = b
    return True


def optimal_by_forest(g, s, edges, price):
    forest = []
    for t in sorted(range(len(edges)), key=price.__getitem__, reverse=True):
        if acyclic(g, s, [edges[i] for i in forest] + [edges[t]]):
            forest.append(t)
    return sum(price) - sum(price[i] for i in forest)


def enumerate_tables(g, s):


    edges = tuple(product(range(g), range(s)))
    maps = []
    for counts in product(range(2), repeat=len(edges)):
        row = tuple(sum(counts[i * s : (i + 1) * s]) for i in range(g))
        col = tuple(sum(counts[j::s]) for j in range(s))
        out = tuple(
            sum((j + 1) * counts[i * s + j] for j in range(s)) for i in range(g)
        )
        maps.append((counts, row + col, out))
    rng = random.Random(g * 19 + s)
    prices = [rng.randrange(1, 11) for _ in edges]
    best = 10**10
    for subset in range(1 << len(edges)):
        observed = [i for i in range(len(edges)) if subset >> i & 1]
        hidden = [e for i, e in enumerate(edges) if not subset >> i & 1]
        results = {}
        trusted = True
        for counts, margins, target in maps:
            data = margins + tuple(counts[i] for i in observed)
            if data in results and results[data] != target:
                trusted = False
                break
            results[data] = target
        assert trusted == acyclic(g, s, hidden), (g, s, observed)
        if trusted:
            best = min(best, sum(prices[i] for i in observed))
    assert best == optimal_by_forest(g, s, edges, prices)
    return len(maps), 1 << len(edges)


if __name__ == "__main__":
    cases = [
        enumerate_tables(g, s) for g, s in ((1, 3), (2, 2), (2, 3), (3, 2), (3, 3))
    ]
    print(
        "checked",
        sum(x[0] for x in cases),
        "binary tables and",
        sum(x[1] for x in cases),
        "distinct measured-cell schedules",
    )
