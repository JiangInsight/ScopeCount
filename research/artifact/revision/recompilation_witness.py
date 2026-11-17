

from itertools import product


def optimal_reads(bought):
    retained = 7 ^ bought
    a, b, c, d = (v & retained for v in (4, 3, 6, 2))
    states = [v for v in range(8) if not v & bought]

    return min(
        sum((root != left, root != right, left != a, left != b, right != c, right != d))
        for root, left, right in product(states, repeat=3)
    )


if __name__ == "__main__":
    costs = [optimal_reads(bought) for bought in range(8)]
    assert (
        costs == [3, 2, 2, 2, 2, 1, 1, 0] and costs[1] + costs[2] < costs[0] + costs[3]
    )
    print("Reoptimized range reads, indexed by purchased mask:", costs)
