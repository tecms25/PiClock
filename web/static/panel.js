/* Makes the control page act on a button press in place, instead of posting
 * and reloading - which threw you back to the top of the page every time.
 *
 * Progressive enhancement: every button is an ordinary form that works on its
 * own. This intercepts the submit when it can, and if anything here fails the
 * form is simply left to post normally.
 *
 * Kept in its own file rather than inline because the panel's
 * Content-Security-Policy is default-src 'self', which blocks inline scripts
 * and inline event handlers outright.
 */
(function () {
  'use strict';

  var flashBox = document.getElementById('panel-flash');
  var stateBox = document.getElementById('service-state');
  var activity = document.getElementById('activity-rows');
  var activityCount = document.getElementById('activity-count');

  function show(message, ok) {
    if (!flashBox) { return; }
    flashBox.textContent = message;
    flashBox.className = 'flash ' + (ok ? 'ok' : 'error');
    flashBox.hidden = false;
  }

  function renderState(service) {
    if (!stateBox || !service) { return; }
    var active = service.available ? service.active : 'unknown';
    stateBox.textContent = active;
    stateBox.className = 'state ' + (
      !service.available ? 'unknown' : (active === 'active' ? 'good' : 'bad'));
  }

  function renderActivity(events) {
    if (!activity || !events) { return; }
    // Built with textContent rather than innerHTML: these rows carry command
    // output and source addresses, and none of it should ever be parsed as
    // markup.
    activity.textContent = '';
    events.forEach(function (e) {
      var row = document.createElement('tr');
      [e.at, e.address, e.action].forEach(function (value) {
        var cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      });
      var outcome = document.createElement('td');
      outcome.textContent = e.outcome;
      outcome.className = e.outcome === 'ok' ? 'good' : 'bad';
      row.appendChild(outcome);
      var detail = document.createElement('td');
      detail.textContent = e.detail;
      row.appendChild(detail);
      activity.appendChild(row);
    });
    if (activityCount) { activityCount.textContent = events.length; }
  }

  function submit(form) {
    // Disabled only, never relabelled: the label holds a <kbd> element, and
    // rebuilding it would mean touching innerHTML for no benefit.
    var button = form.querySelector('button');
    if (button) { button.disabled = true; }

    fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    }).then(function (response) {
      // A 400 or 403 still carries a JSON body worth showing.
      return response.json().catch(function () {
        return { ok: false, message: 'The panel returned an unexpected reply (' +
                 response.status + ').' };
      });
    }).then(function (data) {
      show(data.message || 'Done.', !!data.ok);
      renderState(data.service);
      renderActivity(data.events);
    }).catch(function () {
      show('Could not reach the panel. It may have restarted - reload the page.',
           false);
    }).then(function () {
      if (button) { button.disabled = false; }
    });
  }

  /* Settings filter: hide rows whose name or help does not match. */
  var filter = document.getElementById('settings-filter');
  if (filter) {
    filter.addEventListener('input', function () {
      var needle = filter.value.trim().toLowerCase();
      Array.prototype.forEach.call(
        document.querySelectorAll('tr.setting'), function (row) {
          row.hidden = needle !== '' &&
            row.textContent.toLowerCase().indexOf(needle) === -1;
        });
    });
  }

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form.hasAttribute || !form.hasAttribute('data-live')) { return; }
    var question = form.getAttribute('data-confirm');
    if (question && !window.confirm(question)) {
      event.preventDefault();
      return;
    }
    event.preventDefault();
    submit(form);
  });
}());
