# ReviewInsight preview

A clickable preview of ReviewInsight, built on real review data.

Every review count, rating, date and quote is pulled from G2, Capterra, Gartner Peer
Insights and Trustpilot, and links back to its source. 1,975 reviews across 16 vendors
in two categories.

## The score

    rating   = the four sites' own averages, averaged, x20
    evidence = 0.30 Recent + 0.25 Reliable + 0.25 Results + 0.20 Resonance
    score    = 50 + (rating - 50) x evidence / 100

A product with perfect evidence scores exactly what reviewers rate it. A product with no
usable evidence sits at 50. Every vendor page shows the full arithmetic.

## Rebuilding it

    python src/pull.py       # ratings, counts, quotes per site
    python src/deep.py       # review-level records at depth
    python src/classify.py   # label each review for outcomes and tone
    python src/score.py      # compute the four Rs and the score
    python src/build.py      # render the site

Editorial and independent. Vendors cannot buy a listing, a rank, or a removal.
