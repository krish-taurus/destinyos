// Same-origin: nginx proxies /api/* to the FastAPI service on 127.0.0.1:8100.
window.DESTINY_API = "";
// Flip to true once MSG91 SMS is live. Until then every "Free report" button opens WhatsApp instead,
// because sign-up codes can't be delivered by SMS yet.
window.DESTINY_SIGNUP_OPEN = false;
window.DESTINY_WHATSAPP = "https://wa.me/917975554666?text=" + encodeURIComponent("Hi, I'd like my free Destiny OS report");
