from apps.site_health.wp_activity_seq import check_sequence


def test_contiguous_batch_has_no_gap():
    assert check_sequence(10, [11, 12, 13]) is None


def test_first_ever_batch_has_no_gap():
    assert check_sequence(0, [1, 2, 3]) is None


def test_gap_requests_resend_from_next_expected():
    assert check_sequence(10, [15, 16]) == 11


def test_replayed_batch_is_not_a_gap():
    # Already-seen rows: the ack was lost, not the batch. Accept, don't resend.
    assert check_sequence(20, [18, 19, 20]) is None


def test_partially_replayed_batch_is_not_a_gap():
    assert check_sequence(20, [19, 20, 21, 22]) is None


def test_buffer_reset_requests_resend_from_zero():
    # MalCare's offset_reset_required: MAX(id) below our stored offset means the
    # table was truncated or recreated. Ask for everything it still holds.
    assert check_sequence(500, [1, 2, 3]) == 0


def test_empty_batch_has_no_gap():
    assert check_sequence(10, []) is None


def test_batch_is_judged_on_its_minimum_not_its_first_element():
    # First element 15 looks like a gap, but 12 is present — and 12 is still
    # above the 11 we expected, so a resend is correct. What matters is that the
    # minimum drives the decision, not the arrival order.
    assert check_sequence(10, [15, 12, 14]) == 11
