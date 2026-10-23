import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { currentSection } from './section-spy';

const view = { covered: 70, height: 800, atBottom: false };

describe('currentSection', () => {
  it('is nothing before the first section reaches the top', () => {
    const sections = [
      { id: 'tasks', top: 300, bottom: 700 },
      { id: 'week', top: 720, bottom: 1400 },
    ];
    assert.equal(currentSection(sections, view), null);
  });

  it('is the section whose top most recently passed under the pinned bar', () => {
    const sections = [
      { id: 'tasks', top: -400, bottom: 60 },
      { id: 'week', top: 80, bottom: 700 },
      { id: 'family', top: 720, bottom: 1400 },
    ];
    assert.equal(currentSection(sections, view), 'week');
  });

  it('ignores a section scrolled away above the pinned bar', () => {
    const sections = [
      { id: 'tasks', top: -900, bottom: 40 },
      { id: 'week', top: -200, bottom: 600 },
    ];
    assert.equal(currentSection(sections, view), 'week');
  });

  it('picks the nearest top when two sections sit side by side', () => {
    const sections = [
      { id: 'chart', top: -50, bottom: 400 },
      { id: 'tasks', top: 60, bottom: 900 },
    ];
    assert.equal(currentSection(sections, view), 'tasks');
  });

  it('at the very bottom, picks the lowest section on screen, even if it never reached the top', () => {
    const sections = [
      { id: 'week', top: -300, bottom: 500 },
      { id: 'notes', top: 600, bottom: 780 },
    ];
    assert.equal(currentSection(sections, { ...view, atBottom: true }), 'notes');
  });

  it('keeps a section just jumped to, while it is on screen', () => {
    const sections = [
      { id: 'week', top: -300, bottom: 500 },
      { id: 'notes', top: 600, bottom: 780 },
    ];
    assert.equal(currentSection(sections, { ...view, jumpedTo: 'notes' }), 'notes');
    assert.equal(currentSection(sections, { ...view, jumpedTo: 'gone' }), 'week');
  });
});
