"""The three things Kevin was explicit about, asserted."""
import rating


def sites(*pairs):
    return [(f"P{i}", {"rating": r, "count": c}) for i, (r, c) in enumerate(pairs)]


def review_avg(pairs):
    total = sum(c for _, c in pairs)
    return round(sum(r * c for r, c in pairs) / total, 2)


def reliable(pairs):
    gap = max(r for r, _ in pairs) - min(r for r, _ in pairs)
    agree, _ = rating.curve("agreement", round(gap, 2))
    return round(agree * rating.PRESENCE.get(len(pairs), 1.0), 1)


def main() -> None:
    fails = []

    # 1. Review Avg counts every review once, not every platform once.
    got = review_avg([(4.9, 55), (1.0, 2)])
    print(f"Review Avg, Kevin's example        {got}  (expected 4.76)")
    if got != 4.76:
        fails.append("review avg")

    # 2. A brand on one platform cannot score well on Reliable, however tidy
    #    that single rating is.
    one = reliable([(4.6, 900)])
    four = reliable([(4.6, 900), (4.6, 400), (4.6, 200), (4.6, 100)])
    print(f"Reliable, one platform             {one}")
    print(f"Reliable, four platforms, no gap   {four}")
    if not one < four * 0.5:
        fails.append("single-platform penalty")

    # 3. Differences in review COUNT must never count against a brand.
    #    Same ratings, wildly different volumes, identical Reliable.
    even = reliable([(4.5, 500), (4.4, 500)])
    lopsided = reliable([(4.5, 9000), (4.4, 12)])
    print(f"Reliable, even counts              {even}")
    print(f"Reliable, lopsided counts          {lopsided}")
    if even != lopsided:
        fails.append("count variance leaked into Reliable")

    # 4. A wide gap has to bite hard.
    tight = reliable([(4.6, 100), (4.5, 100), (4.6, 100), (4.4, 100)])
    wide = reliable([(4.6, 100), (4.5, 100), (4.4, 100), (1.5, 100)])
    print(f"Reliable, tight agreement          {tight}")
    print(f"Reliable, one platform way off     {wide}")
    if wide > 25:
        fails.append("gap penalty too soft")

    print()
    print("FAILED: " + ", ".join(fails) if fails else "all four constraints hold")


if __name__ == "__main__":
    main()
