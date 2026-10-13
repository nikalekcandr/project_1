/* =====================================================================
   ЛОГИКА САЙТА — обычно этот файл трогать не нужно.
   Все настройки (контакты, тема, анкета, аналитика) — в config.js
   ===================================================================== */

(function () {
  "use strict";

  const cfg = window.SITE_CONFIG || {};
  const contacts = cfg.contacts || {};
  const root = document.documentElement;
  window.SITE_READY = true;

  /* ---------- Контакты: подставляем ссылки из config.js ---------- */

  const digits = (s) => String(s || "").replace(/\D/g, "");

  const links = {
    telegram: contacts.telegram && "https://t.me/" + contacts.telegram.replace(/^@/, ""),
    whatsapp: digits(contacts.whatsapp) && "https://wa.me/" + digits(contacts.whatsapp),
    email: contacts.email && "mailto:" + contacts.email,
    phone: contacts.phone && "tel:+" + digits(contacts.phone),
  };

  const formatPhone = (raw) => {
    const d = digits(raw);
    if (d.length === 11 && (d[0] === "7" || d[0] === "8")) {
      return `+7 ${d.slice(1, 4)} ${d.slice(4, 7)}-${d.slice(7, 9)}-${d.slice(9)}`;
    }
    return d ? "+" + d : "";
  };

  const labels = {
    telegram: contacts.telegram && "@" + contacts.telegram.replace(/^@/, ""),
    whatsapp: formatPhone(contacts.whatsapp),
    email: contacts.email,
    phone: contacts.phone,
  };

  document.querySelectorAll("[data-contact]").forEach((el) => {
    const type = el.dataset.contact;
    const href = links[type];
    if (href) {
      el.href = href;
      if (/^https?:/.test(href)) { el.target = "_blank"; el.rel = "noopener"; }
      el.addEventListener("click", () => track("contact_click", { method: type }));
    } else if (el.matches(".contact-btn, .social")) {
      el.hidden = true; // контакт не указан — прячем кнопку
    }
    // Остальные кнопки без контакта просто ведут к разделу «Контакты»
  });

  document.querySelectorAll("[data-contact-label]").forEach((el) => {
    const value = labels[el.dataset.contactLabel];
    if (value) el.textContent = value;
  });

  /* ---------- Шапка: фон при прокрутке ---------- */

  const header = document.querySelector(".header");
  const sticky = document.querySelector(".sticky-cta");
  const contactSection = document.getElementById("contact");
  let contactVisible = false;

  const onScroll = () => {
    const y = window.scrollY;
    header && header.classList.toggle("is-scrolled", y > 10);
    sticky && sticky.classList.toggle("is-visible", y > 640 && !contactVisible);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  if (contactSection && "IntersectionObserver" in window) {
    new IntersectionObserver(([entry]) => { contactVisible = entry.isIntersecting; onScroll(); })
      .observe(contactSection);
  }

  /* ---------- Мобильное меню ---------- */

  const burger = document.querySelector(".burger");
  const nav = document.getElementById("nav");

  const setMenu = (open) => {
    document.body.classList.toggle("menu-open", open);
    burger && burger.setAttribute("aria-expanded", String(open));
    burger && burger.setAttribute("aria-label", open ? "Закрыть меню" : "Открыть меню");
  };

  burger && burger.addEventListener("click", () => setMenu(!document.body.classList.contains("menu-open")));
  nav && nav.addEventListener("click", (e) => { if (e.target.closest("a")) setMenu(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });
  window.matchMedia("(min-width: 921px)").addEventListener("change", (e) => { if (e.matches) setMenu(false); });

  /* ---------- Плавное появление блоков ---------- */

  // Небольшая задержка для элементов в одной группе — «волна»
  document.querySelectorAll(".cards-3, .bento, .tests, .steps, .plans, .faq__list, .methods").forEach((group) => {
    group.querySelectorAll(":scope > .reveal").forEach((el, i) => el.style.setProperty("--d", Math.min(i * 0.08, 0.48) + "s"));
  });

  const reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-in");
        io.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    reveals.forEach((el) => io.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add("is-in"));
  }

  /* ---------- Счётчики на первом экране ---------- */

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduceMotion) {
    document.querySelectorAll("[data-count]").forEach((el) => {
      const target = parseInt(el.dataset.count, 10);
      if (!target) return;
      const start = performance.now();
      const duration = 1400;
      el.textContent = "0";
      const tick = (now) => {
        const p = Math.min((now - start) / duration, 1);
        el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
        if (p < 1) requestAnimationFrame(tick);
      };
      setTimeout(() => requestAnimationFrame((t) => { tick(t); }), 400);
    });
  }

  /* ---------- Год в подвале ---------- */

  document.querySelectorAll("[data-year]").forEach((el) => (el.textContent = new Date().getFullYear()));

  /* ---------- Уведомление ---------- */

  const toastEl = document.querySelector(".toast");
  let toastTimer;
  const toast = (msg) => {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("is-visible"), 4500);
  };

  /* ---------- Анкета ---------- */

  const form = document.getElementById("lead-form");
  const formCfg = cfg.form || {};

  if (form && formCfg.enabled === false) {
    form.hidden = true;
    form.closest(".contact") && form.closest(".contact").classList.add("contact--no-form");
  }

  const copyText = (text) => {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).catch(() => {});
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) { /* ничего */ }
    ta.remove();
    return Promise.resolve();
  };

  const openUrl = (url) => {
    const w = window.open(url, "_blank");
    if (w) w.opener = null;
    else window.location.href = url; // браузер заблокировал новую вкладку — открываем в этой
  };

  if (form && formCfg.enabled !== false) {
    const status = form.querySelector(".form__status");
    const setStatus = (msg, type) => {
      status.textContent = msg;
      status.className = "form__status" + (type ? " is-" + type : "");
    };

    form.addEventListener("input", (e) => {
      e.target.classList.remove("is-invalid");
      e.target.closest(".consent") && e.target.closest(".consent").classList.remove("is-invalid");
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      // Проверка обязательных полей
      let ok = true;
      ["name", "contact"].forEach((n) => {
        const input = form.elements[n];
        const bad = !input.value.trim();
        input.classList.toggle("is-invalid", bad);
        if (bad) ok = false;
      });
      const consent = form.elements.consent;
      consent.closest(".consent").classList.toggle("is-invalid", !consent.checked);
      if (!consent.checked) ok = false;
      if (!ok) { setStatus("Заполните имя, контакт и отметьте согласие", "error"); return; }

      const data = {
        name: form.elements.name.value.trim(),
        city: form.elements.city.value.trim(),
        contact: form.elements.contact.value.trim(),
        format: (form.querySelector("input[name=format]:checked") || {}).value || "",
        message: form.elements.message.value.trim(),
      };

      const text = "Здравствуйте! Пишу с вашего сайта.\n\n" + [
        "Имя: " + data.name,
        data.city && "Город: " + data.city,
        "Контакт: " + data.contact,
        data.format && "Формат: " + data.format,
        data.message && "О себе: " + data.message,
      ].filter(Boolean).join("\n");

      // Куда отправлять: выбранный канал или первый доступный
      let channel = formCfg.sendTo || "telegram";
      const messengerOk = { telegram: !!links.telegram, whatsapp: !!links.whatsapp, email: !!links.email };
      if (channel in messengerOk && !messengerOk[channel]) {
        channel = ["telegram", "whatsapp", "email"].find((c) => messengerOk[c]) || channel;
      }

      track("form_submit", { method: channel });

      try {
        if (channel === "web3forms" || channel === "formspree") {
          const btn = form.querySelector("[type=submit]");
          btn.disabled = true;
          setStatus("Отправляю…");
          let res;
          if (channel === "web3forms") {
            res = await fetch("https://api.web3forms.com/submit", {
              method: "POST",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify({ access_key: formCfg.web3formsKey, subject: "Новая анкета с сайта", ...data }),
            });
          } else {
            res = await fetch("https://formspree.io/f/" + formCfg.formspreeId, {
              method: "POST",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify(data),
            });
          }
          btn.disabled = false;
          if (!res.ok) throw new Error("send failed");
          form.reset();
          setStatus("Спасибо! Анкета отправлена — я свяжусь с вами в течение дня.", "success");
          return;
        }

        if (channel === "whatsapp") {
          openUrl(links.whatsapp + "?text=" + encodeURIComponent(text));
          setStatus("Открываю WhatsApp — осталось нажать «Отправить».", "success");
        } else if (channel === "email") {
          window.location.href = links.email + "?subject=" + encodeURIComponent("Анкета с сайта") + "&body=" + encodeURIComponent(text);
          setStatus("Открываю почту — осталось нажать «Отправить».", "success");
        } else {
          copyText(text);
          openUrl(links.telegram + "?text=" + encodeURIComponent(text));
          setStatus("Текст анкеты скопирован. Вставьте его в чат Telegram и отправьте.", "success");
          toast("Текст скопирован — вставьте его в чат");
        }
      } catch (err) {
        const btn = form.querySelector("[type=submit]");
        btn.disabled = false;
        setStatus("Не получилось отправить. Напишите, пожалуйста, напрямую в мессенджер.", "error");
      }
    });
  }

  /* ---------- Аналитика (включается в config.js) ---------- */

  const an = cfg.analytics || {};

  if (an.yandexMetrika) {
    (function (m, e, t, r, i, k, a) {
      m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
      m[i].l = 1 * new Date();
      k = e.createElement(t); a = e.getElementsByTagName(t)[0];
      k.async = 1; k.src = r; a.parentNode.insertBefore(k, a);
    })(window, document, "script", "https://mc.yandex.ru/metrika/tag.js", "ym");
    window.ym(Number(an.yandexMetrika), "init", { clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: true });
  }

  if (an.googleAnalytics) {
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + an.googleAnalytics;
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag("js", new Date());
    window.gtag("config", an.googleAnalytics);
  }

  // Цели: клики по мессенджерам и отправка анкеты
  function track(goal, params) {
    try {
      if (an.yandexMetrika && window.ym) window.ym(Number(an.yandexMetrika), "reachGoal", goal, params);
      if (an.googleAnalytics && window.gtag) window.gtag("event", goal, params);
    } catch (e) { /* аналитика не должна ломать сайт */ }
  }

  root.classList.add("is-ready");
})();
