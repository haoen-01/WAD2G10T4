import { storeToRefs } from 'pinia';

import type { Appointment } from '@/lib/family';
import { AUTH_ENABLED } from '@/lib/config';
import { useCalendarStore } from '@/stores/calendar';

/**
 * The family calendar, shared by Home, Calendar, Family and the senior's own screen. The state lives
 * in the Pinia calendar store (`stores/calendar.ts`); this keeps the shape every screen already
 * uses: the appointments and member state as the store's own reactive objects, its other state and
 * getters as refs (`storeToRefs`), and its actions.
 */
export { announceFamilyChange, onFamilyChange } from '@/stores/calendar';
export type { FamilyChange } from '@/stores/calendar';

/** The calendar's appointments as last read, for the walk check-in (no alert at an appointment). */
export function calendarAppointments(): readonly Appointment[] {
  return useCalendarStore().appointments;
}

export function useFamily() {
  const store = useCalendarStore();
  // Every screen that shows the calendar reads it fresh when it opens.
  void store.refresh();
  const { elderName, loading, loaded, error, groupId, personId, currentMember } =
    storeToRefs(store);
  return {
    elderName,
    today: store.today,
    appointments: store.appointments,
    state: store.state,
    loading,
    loaded,
    error,
    groupId,
    personId,
    currentMember,
    /** Sign-in off only: the demo can switch between family members. */
    canViewAs: !AUTH_ENABLED,
    refresh: store.refresh,
    setCurrentMember: store.setCurrentMember,
    addAvailability: store.addAvailability,
    removeAvailability: store.removeAvailability,
    respond: store.respond,
    volunteer: store.volunteer,
    stepBack: store.stepBack,
    addAppointment: store.addAppointment,
    updateAppointment: store.updateAppointment,
    moveAppointment: store.moveAppointment,
    paintDay: store.paintDay,
    pickDayPart: store.pickDayPart,
    removeAppointment: store.removeAppointment,
    statusOf: store.statusOf,
    helperIdsOf: store.helperIdsOf,
  };
}
