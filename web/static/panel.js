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
  var audioBox = document.getElementById('audio-state');

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

  var volumeInput = document.getElementById('volume');
  var volumeValue = document.getElementById('volume-value');
  var adjusting = false;

  function renderAudio(state) {
    if (!audioBox || typeof state !== 'string') { return; }
    audioBox.textContent = state;
    audioBox.hidden = state === '';
  }

  function renderVolume(level) {
    // Ignored mid-drag: a poll landing while the slider is being moved would
    // otherwise yank it back to where it was a moment ago.
    if (!volumeInput || adjusting || typeof level !== 'number') { return; }
    volumeInput.value = level;
    if (volumeValue) { volumeValue.textContent = level + '%'; }
  }

  if (volumeInput) {
    // 'input' fires continuously while dragging - used only to update the
    // number - and 'change' fires once on release, which is what gets sent.
    volumeInput.addEventListener('input', function () {
      adjusting = true;
      if (volumeValue) { volumeValue.textContent = volumeInput.value + '%'; }
    });
    volumeInput.addEventListener('change', function () {
      adjusting = false;
      var form = volumeInput.form;
      if (!form) { return; }
      if (form.requestSubmit) {
        form.requestSubmit();      // goes through the data-live handler below
      } else {
        submit(form);
      }
    });
  }

  /* A stream can fail a second or two after it starts, so the reply to the
   * Play button is too early to be the last word. Ask the panel now and then
   * instead of leaving a stale line on screen. Paused while the tab is hidden,
   * because nobody is reading it and each poll asks the clock. */
  function startAudioPolling() {
    if (!audioBox) { return; }
    setInterval(function () {
      if (document.hidden) { return; }
      fetch('/api/audio', {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
      }).then(function (r) {
        return r.ok ? r.json() : null;
      }).then(function (data) {
        if (data) { renderAudio(data.state); renderVolume(data.volume); }
      }).catch(function () { /* a blip; the next poll can try again */ });
    }, 5000);
  }

  // The clock answers the camera list from a cache it fills in the background,
  // so a panel opened right after a restart gets an empty list first. Poll
  // until it arrives, then stop: cameras are not added to Blue Iris while
  // somebody watches this page, and the page is rebuilt on every visit.
  function renderCameras(cameras) {
    var box = document.getElementById('camera-actions');
    var empty = document.getElementById('camera-empty');
    var count = document.getElementById('camera-count');
    if (!box || !cameras) { return false; }
    if (Number(count && count.textContent) === cameras.length) {
      return cameras.length > 0;
    }
    var dismiss = box.lastElementChild;
    Array.prototype.slice.call(box.querySelectorAll('form')).forEach(
      function (form) { if (form !== dismiss) { box.removeChild(form); } });
    cameras.forEach(function (camera) {
      var form = document.createElement('form');
      form.method = 'post';
      form.action = box.getAttribute('data-command-url') || '/command';
      form.setAttribute('data-live', '');
      // textContent throughout: a camera name comes from Blue Iris, and the
      // page must not build markup out of it.
      [['csrf', csrfToken()], ['command', 'camera_show'],
       ['camera', camera.name]].forEach(function (pair) {
        var field = document.createElement('input');
        field.type = 'hidden';
        field.name = pair[0];
        field.value = pair[1];
        form.appendChild(field);
      });
      var button = document.createElement('button');
      button.type = 'submit';
      button.className = 'secondary';
      button.textContent = 'Show';
      form.appendChild(button);
      var label = document.createElement('span');
      label.className = 'muted';
      label.textContent = camera.label || camera.name;
      form.appendChild(label);
      box.insertBefore(form, dismiss);
    });
    if (count) { count.textContent = String(cameras.length); }
    if (empty) { empty.hidden = cameras.length > 0; }
    return cameras.length > 0;
  }

  function csrfToken() {
    var field = document.querySelector('input[name="csrf"]');
    return field ? field.value : '';
  }

  function startCameraPolling() {
    if (!document.getElementById('camera-actions')) { return; }
    if (Number(document.getElementById('camera-count').textContent) > 0) {
      return;  // the page was rendered with the list already
    }
    var timer = setInterval(function () {
      if (document.hidden) { return; }
      fetch('/api/cameras', {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
      }).then(function (r) {
        return r.ok ? r.json() : null;
      }).then(function (data) {
        if (data && renderCameras(data.cameras)) { clearInterval(timer); }
      }).catch(function () { /* a blip; the next poll can try again */ });
    }, 4000);
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

    // getAttribute, never form.action. A form's named controls are exposed as
    // properties of the form element, so the hidden <input name="action"> in
    // every action form shadows HTMLFormElement.action - and fetch() then
    // stringifies that element, posting to /[object HTMLInputElement] and
    // getting a 404. The attribute is not shadowed.
    var target = form.getAttribute('action') || window.location.pathname;

    fetch(target, {
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
      renderAudio(data.audio);
      renderVolume(data.volume);
      renderActivity(data.events);
    }).catch(function () {
      show('Could not reach the panel. It may have restarted - reload the page.',
           false);
    }).then(function () {
      if (button) { button.disabled = false; }
    });
  }

  /* Settings filter: hide rows that do not match, and open any group holding
   * one - otherwise a match inside a collapsed group looks like no match at
   * all. Groups the user opened by hand before typing are remembered, so
   * clearing the box puts the page back as it was rather than collapsing
   * everything. */
  var filter = document.getElementById('settings-filter');
  if (filter) {
    var wasOpen = null;

    filter.addEventListener('input', function () {
      var needle = filter.value.trim().toLowerCase();
      var groups = document.querySelectorAll('details.group');

      if (needle === '') {
        Array.prototype.forEach.call(groups, function (group, i) {
          // hidden must be cleared whether or not a previous state was saved,
          // or a group the filter hid stays invisible after clearing the box.
          group.hidden = false;
          if (wasOpen) { group.open = wasOpen[i]; }
        });
        wasOpen = null;
        Array.prototype.forEach.call(
          document.querySelectorAll('.setting'), function (row) {
            row.hidden = false;
          });
        return;
      }

      if (!wasOpen) {
        wasOpen = Array.prototype.map.call(groups, function (g) { return g.open; });
      }

      Array.prototype.forEach.call(groups, function (group) {
        var hits = 0;
        Array.prototype.forEach.call(
          group.querySelectorAll('.setting'), function (row) {
            var match = row.textContent.toLowerCase().indexOf(needle) !== -1;
            row.hidden = !match;
            if (match) { hits += 1; }
          });
        group.open = hits > 0;
        group.hidden = hits === 0;
      });
    });
  }

  /* Live screenshot of the clock, for working on one you cannot see. Loaded
   * only when asked for: each frame makes the clock render and encode a
   * full-screen image, which is real work on a Pi. */
  var shotImage = document.getElementById('shot-image');
  var shotNote = document.getElementById('shot-note');
  var shotAuto = document.getElementById('shot-auto');
  var shotTimer = null;
  var shotBusy = false;

  function loadShot() {
    if (!shotImage || shotBusy) { return; }
    shotBusy = true;
    if (shotNote) { shotNote.textContent = 'Capturing...'; }
    // A changing query string, or the browser shows the previous capture.
    var probe = new Image();
    probe.onload = function () {
      shotImage.src = probe.src;
      shotBusy = false;
      if (shotNote) {
        shotNote.textContent = 'Captured ' + new Date().toLocaleTimeString();
      }
    };
    probe.onerror = function () {
      shotBusy = false;
      if (shotNote) {
        shotNote.textContent = 'Could not capture - is the clock running?';
      }
    };
    probe.src = '/screenshot.jpg?w=960&t=' + Date.now();
  }

  function setShotAuto(on) {
    if (shotTimer) { clearInterval(shotTimer); shotTimer = null; }
    if (!on) { return; }
    // Deliberately unhurried: this is for watching a clock change, not video.
    shotTimer = setInterval(function () {
      if (!document.hidden) { loadShot(); }
    }, 5000);
  }

  var shotButton = document.getElementById('shot-refresh');
  if (shotButton) { shotButton.addEventListener('click', loadShot); }
  if (shotAuto) {
    shotAuto.addEventListener('change', function () {
      setShotAuto(shotAuto.checked);
      if (shotAuto.checked) { loadShot(); }
    });
  }
  if (shotImage) { loadShot(); }

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form.hasAttribute) { return; }

    // Confirmation is independent of how the form is sent, so a form that
    // reloads the page can still ask first.
    var question = form.getAttribute('data-confirm');
    if (question && !window.confirm(question)) {
      event.preventDefault();
      return;
    }

    // Only data-live forms are sent by fetch. The rest post normally, which is
    // what a page whose contents change - the settings - actually wants.
    if (!form.hasAttribute('data-live')) { return; }
    event.preventDefault();
    submit(form);
  });

  startAudioPolling();
  startCameraPolling();
}());
