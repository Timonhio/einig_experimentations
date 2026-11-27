// A10 (D16, D20, D29): swipe the rating card. Right = "Rather yes", up = "Fine with me",
// left = "Rather not", down = asks whether to use the joker. This works on every page of the card.
// U6: a short tap on the right half shows the next page, on the left half the previous one
// (like stories); the three bars at the top show the page and can be tapped too.
// This script only presses buttons that are already on the page; the normal forms do the rest.
// Without this script the page works the same, with the (visually hidden) buttons.
(function () {
  "use strict";

  var SWIPE_DISTANCE = 110;  // pixels the card must be moved before a swipe counts
  var TAP_DISTANCE = 10;     // a touch that moves less than this is a tap: it changes the page (D29)
  var FLY_OUT_MS = 200;      // length of the fly-out animation before the button is pressed

  var card = document.querySelector("[data-swipe-card]");
  if (!card) {
    return;  // not the one-card rating view: nothing to do
  }
  var area = card.querySelector("[data-swipe-area]");
  var pageBox = card.querySelector("[data-card-pages]");      // only on Google cards with details
  var pages = card.querySelectorAll("[data-card-page]");
  var bars = card.querySelectorAll("[data-card-bar]");
  var question = card.querySelector("[data-joker-question]");  // only while the joker is still free
  var jokerButton = card.querySelector('form[action$="/veto"] button');
  var buttons = {
    yes: card.querySelector('button[name="rating"][value="yes"]'),
    ok: card.querySelector('button[name="rating"][value="ok"]'),
    no: card.querySelector('button[name="rating"][value="no"]')
  };
  if (!area || !buttons.yes || !buttons.ok || !buttons.no) {
    return;
  }

  // Swiping works now, so the rating buttons may be hidden (app.css). Without this script they stay visible.
  card.classList.add("swipe-ready");

  // Show the hint only now that swiping works.
  var hint = document.querySelector("[data-swipe-hint]");
  if (hint) {
    hint.hidden = false;
  }

  // Show page number `index` (0, 1 or 2) and mark its bar. Without this script CSS uses :target.
  var current = 0;
  function showPage(index) {
    if (index < 0 || index >= pages.length) { return; }  // no page before the first or after the last
    current = index;
    for (var i = 0; i < pages.length; i++) {
      pages[i].classList.toggle("is-current", i === index);
      if (bars[i]) {
        if (i === index) {
          bars[i].setAttribute("aria-current", "true");
        } else {
          bars[i].removeAttribute("aria-current");
        }
      }
    }
  }
  if (pageBox && pages.length) {
    // Start on the page the address points to (a bar used before the script ran), else page 1.
    for (var p = 0; p < pages.length; p++) {
      if (window.location.hash === "#" + pages[p].id) { current = p; }
    }
    pageBox.classList.add("pages-ready");  // from now on CSS shows .is-current, not :target
    showPage(current);
    for (var b = 0; b < bars.length; b++) {
      bars[b].addEventListener("click", (function (index) {
        return function (event) {
          event.preventDefault();  // change the page without jumping to the anchor
          showPage(index);
        };
      })(b));
    }
  }

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var start = null;   // where the finger went down, or null when not dragging
  var done = false;   // true after one swipe counted: ignore everything until the next page

  // Which rating a movement would give, or null. Down gives nothing here: it asks about the joker.
  function choiceFor(dx, dy) {
    if (Math.abs(dx) > Math.abs(dy)) {
      if (dx >= SWIPE_DISTANCE) { return "yes"; }
      if (dx <= -SWIPE_DISTANCE) { return "no"; }
    } else if (dy <= -SWIPE_DISTANCE) {
      return "ok";
    }
    return null;
  }

  // Move and tilt the card with the finger, and show the label of the rating it would give.
  function moveCard(dx, dy) {
    card.style.transform = "translate(" + dx + "px, " + dy + "px) rotate(" + dx / 20 + "deg)";
    var choice = choiceFor(dx, dy);
    // D1b: a long swipe down shows "Joker?" as a label only; choiceFor() never gives it, so the
    // release still just asks the question and nothing is rated.
    if (!choice && question && dy >= SWIPE_DISTANCE && Math.abs(dy) > Math.abs(dx)) {
      choice = "joker";
    }
    if (choice) {
      card.setAttribute("data-swipe-choice", choice);
    } else {
      card.removeAttribute("data-swipe-choice");
    }
  }

  // Put the card back where it was; nothing is sent.
  function springBack() {
    card.classList.remove("is-dragging");
    card.style.transform = "";
    card.removeAttribute("data-swipe-choice");
  }

  area.addEventListener("pointerdown", function (event) {
    if (done) { return; }
    // A touch that starts on a link (e.g. the photo author) is left alone: the link works normally.
    if (event.target.closest("a")) { return; }
    start = { x: event.clientX, y: event.clientY };
    card.classList.add("is-dragging");
    area.setPointerCapture(event.pointerId);
  });

  area.addEventListener("pointermove", function (event) {
    if (start === null) { return; }
    moveCard(event.clientX - start.x, event.clientY - start.y);
  });

  area.addEventListener("pointerup", function (event) {
    if (start === null) { return; }
    var dx = event.clientX - start.x;
    var dy = event.clientY - start.y;
    var choice = choiceFor(dx, dy);
    start = null;
    // Down: do not use the joker at once, it cannot be undone. Ask first; nothing is sent yet.
    if (!choice && question && dy >= SWIPE_DISTANCE && Math.abs(dy) > Math.abs(dx)) {
      springBack();
      question.hidden = false;
      return;
    }
    if (!choice && pages.length && Math.abs(dx) < TAP_DISTANCE && Math.abs(dy) < TAP_DISTANCE) {
      springBack();
      // A short tap changes the page; nothing is rated. Right half: next, left half: previous.
      var box = area.getBoundingClientRect();
      if (event.clientX >= box.left + box.width / 2) {
        showPage(current + 1);
      } else {
        showPage(current - 1);
      }
      return;
    }
    if (!choice) {
      springBack();
      return;
    }
    done = true;
    card.classList.remove("is-dragging");
    if (reduceMotion) {
      buttons[choice].click();
      return;
    }
    // Let the card fly out in the swipe direction, then press the matching button.
    var away = { yes: "translate(150%, 0) rotate(20deg)", ok: "translate(0, -150%)", no: "translate(-150%, 0) rotate(-20deg)" };
    card.style.transform = away[choice];
    window.setTimeout(function () { buttons[choice].click(); }, FLY_OUT_MS);
  });

  area.addEventListener("pointercancel", function () {
    start = null;
    springBack();
  });

  // The joker question: "Use joker" presses the joker button that is already in the page.
  if (question && jokerButton) {
    question.querySelector("[data-joker-confirm]").addEventListener("click", function () {
      done = true;
      jokerButton.click();
    });
    question.querySelector("[data-joker-cancel]").addEventListener("click", function () {
      question.hidden = true;
    });
  }

  // After one swipe, ignore further taps on the card's buttons (no double rating).
  card.addEventListener("click", function (event) {
    if (done && event.isTrusted) {
      event.preventDefault();
    }
  }, true);
})();
