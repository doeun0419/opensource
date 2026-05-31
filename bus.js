const MONITOR_STREAM_URL = "/video_feed";
const COUNT_STATE_URL = "utils/data/count_state.json";
const MAX_WAITING_COUNT = 60;
const DEFAULT_WAITING_COUNT = 30;
const RESERVATION_STORAGE_KEY = "shuttleReservationCounts";

const elements = {
    brandLink: document.querySelector("[data-view-link]"),
    navTabs: document.querySelectorAll("[data-view]"),
    panels: document.querySelectorAll("[data-panel]"),
    monitorFrame: document.getElementById("monitor-frame"),
    monitorMessage: document.getElementById("monitor-message"),
    bar: document.getElementById("bar"),
    count: document.getElementById("count"),
    percent: document.getElementById("percent"),
    capacityText: document.getElementById("capacity-text"),
    status: document.getElementById("status"),
    connectionStatus: document.getElementById("connection-status"),
    lastUpdated: document.getElementById("last-updated"),
    popup: document.getElementById("popup"),
    popupText: document.getElementById("popup-text"),
    reservationCount: document.getElementById("reservation-count"),
    setAlarmButton: document.getElementById("set-alarm-btn"),
    cancelAlarmButton: document.getElementById("cancel-alarm-btn"),
};

let selectedTime = "";

function getReservationCounts() {
    try {
        return JSON.parse(localStorage.getItem(RESERVATION_STORAGE_KEY)) || {};
    } catch (error) {
        return {};
    }
}

function getReservationCount(time) {
    const counts = getReservationCounts();
    return Number(counts[time]) || 0;
}

function updateReservationCount(time) {
    const count = getReservationCount(time);
    elements.reservationCount.textContent = `현재 예약 ${count}명`;
}

function addReservation(time) {
    const counts = getReservationCounts();
    counts[time] = getReservationCount(time) + 1;
    localStorage.setItem(RESERVATION_STORAGE_KEY, JSON.stringify(counts));
    updateReservationCount(time);
}

function setConnectionState(label, detail) {
    if (!elements.connectionStatus || !elements.lastUpdated) {
        return;
    }

    elements.connectionStatus.textContent = label;
    elements.lastUpdated.textContent = detail;
}

function formatUpdatedTime(date) {
    return `${date.getHours().toString().padStart(2, "0")}:${date.getMinutes().toString().padStart(2, "0")}:${date.getSeconds().toString().padStart(2, "0")} 업데이트`;
}

function getStatus(percent) {
    if (percent >= 100) {
        return { label: "위험", color: "#002C77", className: "danger" };
    }

    if (percent >= 60) {
        return { label: "혼잡", color: "#002C77", className: "warning" };
    }

    return { label: "여유", color: "#00AFEC", className: "" };
}

function updateDashboard(count) {
    const safeCount = Math.max(0, Number(count) || 0);
    const percent = (safeCount / MAX_WAITING_COUNT) * 100;
    const roundedPercent = Math.round(percent);
    const status = getStatus(percent);

    elements.count.textContent = `${safeCount}명`;
    elements.percent.textContent = `${roundedPercent}%`;
    elements.capacityText.textContent = `정원 ${MAX_WAITING_COUNT}명`;
    elements.status.textContent = status.label;
    elements.status.className = status.className;
    elements.bar.style.width = `${Math.min(percent, 100)}%`;
    elements.bar.style.background = status.color;
}

async function loadCountState() {
    try {
        const response = await fetch(`${COUNT_STATE_URL}?t=${Date.now()}`);

        if (!response.ok) {
            setConnectionState("연결 대기", "데이터 파일 확인 중");
            return;
        }

        const data = await response.json();
        updateDashboard(data.current_inside);
        setConnectionState("정상", formatUpdatedTime(new Date()));
    } catch (error) {
        setConnectionState("오프라인", "Python 서버 또는 파일 확인 필요");
    }
}

function startCamera() {
    elements.monitorMessage.style.display = "block";
    elements.monitorFrame.style.display = "none";
    elements.monitorMessage.textContent = "카메라화면을 기다리는 중입니다.";
    elements.monitorFrame.src = `${MONITOR_STREAM_URL}?t=${Date.now()}`;
}

function stopCamera() {
    elements.monitorFrame.removeAttribute("src");
    elements.monitorFrame.style.display = "none";
    elements.monitorMessage.style.display = "block";
}

function setActiveView(view) {
    elements.navTabs.forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.view === view);
    });

    elements.panels.forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.panel === view);
    });

    if (view === "camera") {
        startCamera();
    } else {
        stopCamera();
    }

    window.scrollTo(0, 0);
}

function showMonitorMessage() {
    elements.monitorFrame.style.display = "none";
    elements.monitorMessage.style.display = "block";
    elements.monitorMessage.textContent = "실행화면이 여기에 표시됩니다.";
}

function showMonitorFrame() {
    elements.monitorMessage.style.display = "none";
    elements.monitorFrame.style.display = "block";
}

function openPopup(time) {
    selectedTime = time;
    elements.popupText.textContent = `${selectedTime} 버스 출발 15분 전 알림을 설정하시겠습니까?`;
    updateReservationCount(selectedTime);
    elements.popup.style.display = "flex";
}

function closePopup() {
    elements.popup.style.display = "none";
}

async function ensureNotificationPermission() {
    if (!("Notification" in window)) {
        return "unsupported";
    }

    if (Notification.permission === "default") {
        return Notification.requestPermission();
    }

    return Notification.permission;
}

async function setAlarm() {
    closePopup();
    addReservation(selectedTime);

    const permission = await ensureNotificationPermission();
    const now = new Date();
    const [hour, minute] = selectedTime.split(":").map(Number);
    const target = new Date();

    target.setHours(hour);
    target.setMinutes(minute - 15);
    target.setSeconds(0);
    target.setMilliseconds(0);

    if (target < now) {
        target.setDate(target.getDate() + 1);
    }

    window.setTimeout(() => {
        showNotification(selectedTime);
    }, target - now);

    if (permission === "denied") {
        alert("브라우저 알림이 차단되어 있어 화면 알림으로 알려드릴게요.");
        return;
    }

    alert("알림이 설정되었습니다.");
}

function showNotification(time) {
    if ("Notification" in window && Notification.permission === "granted") {
        new Notification("셔틀버스 알림", {
            body: `${time} 버스 출발 15분 전입니다.`,
        });
        return;
    }

    alert(`${time} 버스 출발 15분 전입니다.`);
}

function bindEvents() {
    elements.brandLink.addEventListener("click", (event) => {
        event.preventDefault();
        setActiveView(elements.brandLink.dataset.viewLink);
    });

    elements.navTabs.forEach((tab) => {
        tab.addEventListener("click", () => setActiveView(tab.dataset.view));
    });

    elements.monitorFrame.addEventListener("load", showMonitorFrame);
    elements.monitorFrame.addEventListener("error", showMonitorMessage);
    elements.cancelAlarmButton.addEventListener("click", closePopup);
    elements.setAlarmButton.addEventListener("click", setAlarm);

    document.querySelectorAll(".time").forEach((button) => {
        button.addEventListener("click", () => openPopup(button.textContent));
    });

    elements.popup.addEventListener("click", (event) => {
        if (event.target === elements.popup) {
            closePopup();
        }
    });
}

bindEvents();
updateDashboard(DEFAULT_WAITING_COUNT);
loadCountState();
window.setInterval(loadCountState, 1000);
