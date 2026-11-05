from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from bpmn8n.workflows.check import WorkflowCheck
from .models import DemoBooking, DemoSlot
from .process import appointment_booking
from .tasks import (AppointmentRequest, Eligibility, PatientMessage, Reservation, clarify_hospital_request,
                    find_hospital_slots, reserve_hospital_slot, validate_hospital_request)


@override_settings(TIME_ZONE="UTC")
class HospitalTest(TestCase):
    def setUp(self):
        self.slot = DemoSlot.objects.create(service="Cardiology", doctor="Dr Example", location="Clinic A",
                                           starts_at=datetime(2026, 11, 10, 9, tzinfo=timezone.utc))
        self.preferences = dict(service="Cardiology", earliest="2026-11-09", latest="2026-11-13", morning=True)

    def reservation(self, **changes):
        return Reservation(**(self.preferences | dict(request_id="R1", patient_id="P1", slot_id=self.slot.pk,
                                                      selected=True) | changes))

    def test_api_discovery_and_request_validation(self):
        response = self.client.post("/api/tasks/validate_hospital_request",
                                    self.preferences | {"registered": True}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valid"])
        invalid = Eligibility(**self.preferences, registered=True, referral_required=True)
        self.assertFalse(validate_hospital_request(None, invalid).valid)
        self.assertFalse(validate_hospital_request(None, Eligibility()).valid)

    def test_live_directory_is_sent_to_chat_and_result_is_reviewable(self):
        with patch("projects.hospital.tasks.Settings.llm_client") as client:
            client.return_value.ask.return_value = self.preferences
            result = clarify_hospital_request(None, PatientMessage(message="Please book a cardiology visit"))
            self.assertEqual(result.service, "Cardiology")
            self.assertIn("Cardiology", client.return_value.ask.call_args.args[0])

    def test_patient_must_select_and_outside_preferences_is_rejected(self):
        self.assertFalse(reserve_hospital_slot(None, self.reservation(selected=False)).booked)
        self.assertFalse(reserve_hospital_slot(None, self.reservation(service="Other")).booked)
        self.assertEqual(DemoBooking.objects.count(), 0)

    def test_replay_is_idempotent_and_slot_conflicts_do_not_double_book(self):
        first = reserve_hospital_slot(None, self.reservation())
        replay = reserve_hospital_slot(None, self.reservation())
        self.assertEqual(first.booking_id, replay.booking_id)
        self.assertTrue(first.booked)
        self.assertIn("Dr Example", first.confirmation)
        self.assertFalse(reserve_hospital_slot(None, self.reservation(request_id="R2", patient_id="P2")).booked)
        self.assertFalse(reserve_hospital_slot(None, self.reservation(patient_id="P2")).booked)
        self.assertEqual(DemoBooking.objects.count(), 1)
        self.assertFalse(find_hospital_slots(None, AppointmentRequest(**self.preferences)).slots_available)

    def test_reservation_checks_selected_slot_beyond_search_page(self):
        for index in range(10):
            DemoSlot.objects.create(service="Cardiology", doctor=f"Doctor {index}", location="Clinic B",
                                    starts_at=datetime(2026, 11, 9, 9, tzinfo=timezone.utc))
        options = find_hospital_slots(None, AppointmentRequest(**self.preferences))
        self.assertNotIn(self.slot.pk, [slot["slot_id"] for slot in options.slots])
        self.assertTrue(reserve_hospital_slot(None, self.reservation()).booked)

    def test_reservation_rechecks_date_and_time_preferences(self):
        self.assertFalse(reserve_hospital_slot(None, self.reservation(latest="2026-11-09")).booked)
        self.assertFalse(reserve_hospital_slot(None, self.reservation(earliest=None)).booked)
        self.slot.starts_at = datetime(2026, 11, 10, 14, tzinfo=timezone.utc)
        self.slot.save()
        self.assertFalse(reserve_hospital_slot(None, self.reservation()).booked)
        self.assertTrue(reserve_hospital_slot(None, self.reservation(morning=False)).booked)

    def test_lost_slot_between_search_and_write_returns_retry(self):
        original = DemoBooking.objects.create

        def concurrent_booking(**kwargs):
            original(request_id="OTHER", patient_id="OTHER", slot=self.slot)
            return original(**kwargs)

        # Force both inserts inside the reservation transaction. The unique slot constraint rejects
        # the second insert and the transaction rolls back, returning a failed attempt to the workflow.
        with patch("projects.hospital.tasks.DemoBooking.objects.create", side_effect=concurrent_booking):
            self.assertFalse(reserve_hospital_slot(None, self.reservation()).booked)

    def test_workflow_contains_recovery_selection_and_staff_paths(self):
        for lane in ("patients", "hospital-staff"):
            Group.objects.create(name=lane)
        workflow = appointment_booking().as_json()
        self.assertEqual(WorkflowCheck(workflow, fetch=lambda _: None).errors, [])
        connections = workflow["connections"]
        self.assertEqual(connections["Booked?"]["main"][1][0]["node"], "C · Find slots")
        self.assertEqual(connections["Valid?"]["main"][1][0]["node"], "0 · Staff referral")
        self.assertEqual(connections["Selected?"]["main"][0][0]["node"], "C · Reserve slot")

