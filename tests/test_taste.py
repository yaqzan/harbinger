"""For you (taste.py): the line fitted on your own star ratings, and where it is left out."""

import unittest

from harbinger import taste

CFG = {"taste": {"min_rated": 4, "weights": {"mc": 1.0, "us": 0.0, "rating": 0.0}, "hours_cap": 40}}


def row(mc=None, stars=None, hours=None, **kw):
    return {"mc": mc, "stars": stars, "hours": hours, **kw}


class Taste(unittest.TestCase):
    def test_higher_review_scores_predict_more_stars_when_you_rate_that_way(self):
        rows = [row(60, 2, 10), row(70, 3, 10), row(80, 4, 10), row(90, 5, 10), row(85), row(65)]
        info = taste.attach(rows, CFG)
        self.assertEqual(info, {"rated": 4})
        self.assertAlmostEqual(rows[4]["taste"], 4.5)
        self.assertAlmostEqual(rows[5]["taste"], 2.5)

    def test_your_stars_never_reach_the_page(self):
        rows = [row(60, 2, 10), row(70, 3, 10), row(80, 4, 10), row(90, 5, 10)]
        taste.attach(rows, CFG)
        self.assertFalse(any("stars" in r for r in rows))

    def test_too_few_rated_games_gives_no_score(self):
        rows = [row(60, 2), row(90, 5), row(80)]
        self.assertIsNone(taste.attach(rows, CFG))
        self.assertFalse(any("taste" in r for r in rows))

    def test_a_game_with_no_review_score_gets_none(self):
        rows = [row(60, 2, 10), row(70, 3, 10), row(80, 4, 10), row(90, 5, 10), row(hours=20)]
        taste.attach(rows, CFG)
        self.assertNotIn("taste", rows[4])

    def test_stays_between_one_and_five(self):
        rows = [row(60, 2, 10), row(70, 3, 10), row(80, 4, 10), row(90, 5, 10), row(100), row(20)]
        taste.attach(rows, CFG)
        self.assertEqual((rows[4]["taste"], rows[5]["taste"]), (5.0, 1.0))

    def test_hours_past_the_cap_count_as_the_cap(self):
        # same review score; you rated the longer games higher
        rows = [row(80, 2, 2), row(80, 3, 5), row(80, 4, 20), row(80, 5, 40), row(70, 3, 5), row(75, 4, 20),
                row(80, hours=40), row(80, hours=600)]
        taste.attach(rows, CFG)
        self.assertEqual(rows[6]["taste"], rows[7]["taste"])

    def test_scores_are_scaled_so_a_missing_one_reweights_the_rest(self):
        sp = {"mc": (75.0, 10.0), "us": (7.0, 1.0)}
        w = {"mc": 0.5, "us": 0.5, "rating": 0.0}
        self.assertAlmostEqual(taste.blend({"mc": 85, "us": 8.0}, w, sp), 1.0)
        self.assertAlmostEqual(taste.blend({"mc": 85}, w, sp), 1.0)
        self.assertIsNone(taste.blend({"rating": 90}, w, sp))

    def test_off_switch(self):
        rows = [row(60, 2), row(70, 3), row(80, 4), row(90, 5)]
        self.assertIsNone(taste.attach(rows, {"taste": {**CFG["taste"], "enabled": False}}))


if __name__ == "__main__":
    unittest.main()
