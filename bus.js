const MONITOR_STREAM_URL = "/video_feed";
const COUNT_STATE_URL = "utils/data/count_state.json";
const MAX_WAITING_COUNT = 60;
const DEFAULT_WAITING_COUNT = 30;
const RESERVATION_STORAGE_KEY = "shuttleReservationCounts";

// 주차장: parking_counter.py 가 별도 포트(기본 8002)에서 스트리밍
const PARKING_STREAM_PORT = 8002;
const PARKING_STREAM_URL = `http://${location.hostname || "localhost"}:${PARKING_STREAM_PORT}/video_feed`;
const PARKING_STATE_URL = "utils/data/parking_state.json";

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
    forecastList: document.getElementById("forecast-list"),
    recommendSection: document.getElementById("recommend-section"),
    recommendBanner: document.getElementById("recommend-banner"),
    parkingFrame: document.getElementById("parking-frame"),
    parkingMessage: document.getElementById("parking-message"),
    parkingStatus: document.getElementById("parking-status"),
    parkingAvailable: document.getElementById("parking-available"),
    parkingCount: document.getElementById("parking-count"),
    parkingCapacity: document.getElementById("parking-capacity"),
    parkingBar: document.getElementById("parking-bar"),
    // New UI elements
    donutCircle: document.getElementById("donut-circle"),
    clock: document.getElementById("clock"),
    dateDisplay: document.getElementById("date-display"),
    infoMain: document.getElementById("info-main"),
    infoSub: document.getElementById("info-sub"),
};

let selectedTime = "";

// ─── 예약 데이터 관련 (서버 API 사용) ──────────────────────────

// 서버에서 받아온 최신 예약 데이터를 메모리에 캐시
let reservationCache = {};

async function fetchReservations() {
    try {
        const res = await fetch("/reservations?t=" + Date.now());
        if (!res.ok) return;
        reservationCache = await res.json();
        updateForecast();
        restoreAlarmButtons();
    } catch (e) {
        // 서버 미연결 시 무시
    }
}

function getReservationCounts() {
    return reservationCache;
}

function getReservationCount(time) {
    return Number(reservationCache[time]) || 0;
}

function updateReservationCount(time) {
    const count = getReservationCount(time);
    elements.reservationCount.textContent = `현재 예약 ${count}명`;
}

async function addReservation(time) {
    try {
        const res = await fetch("/reservations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ time, action: "add" }),
        });
        reservationCache = await res.json();
        updateReservationCount(time);
        updateForecast();
        markAlarmButton(time);
    } catch (e) {
        alert("서버에 연결할 수 없습니다. people_counter.py가 실행 중인지 확인해주세요.");
    }
}

// ─── 추가: 모든 시간표 버튼에서 시간 목록 수집 (중복 제거) ─────

function getAllBusTimes() {
    const seen = new Set();
    const result = [];
    document.querySelectorAll(".time").forEach((btn) => {
        const text = btn.textContent.trim();
        if (!seen.has(text)) {
            seen.add(text);
            const [h, m] = text.split(":").map(Number);
            result.push({ time: text, totalMinutes: h * 60 + m });
        }
    });
    result.sort((a, b) => a.totalMinutes - b.totalMinutes);
    return result;
}

// ─── 추가: 시간대별 예상 혼잡도 목록 렌더링 ───────────────────

function getForecastStatus(percent) {
    if (percent === 0) {
        return { label: "예약 없음", className: "none", color: "rgba(0,44,119,0.18)" };
    }
    if (percent >= 100) {
        return { label: "위험", className: "danger", color: "#c81e1e" };
    }
    if (percent >= 60) {
        return { label: "혼잡", className: "warning", color: "#e66400" };
    }
    return { label: "여유", className: "safe", color: "#00AFEC" };
}

function updateForecast() {
    const allTimes = getAllBusTimes();
    const counts = getReservationCounts();
    const hasSomeReservation = allTimes.some((t) => (counts[t.time] || 0) > 0);

    if (!hasSomeReservation) {
        elements.forecastList.innerHTML = `<p class="forecast-empty">아직 예약된 알림이 없습니다. 시간표에서 시간을 눌러 알림을 설정해보세요.</p>`;
        return;
    }

    elements.forecastList.innerHTML = allTimes
        .filter((t) => (counts[t.time] || 0) > 0)
        .map((t) => {
            const count = counts[t.time] || 0;
            const percent = Math.min((count / MAX_WAITING_COUNT) * 100, 100);
            const status = getForecastStatus(percent);
            return `
                <div class="forecast-row">
                    <span class="forecast-time">${t.time}</span>
                    <div class="forecast-bar-wrap">
                        <div class="forecast-bar-track">
                            <div class="forecast-bar-fill" style="width:${percent}%; background:${status.color};"></div>
                        </div>
                        <span class="forecast-count">${count}명 예약 (정원 ${MAX_WAITING_COUNT}명 기준 ${Math.round(percent)}%)</span>
                    </div>
                    <span class="forecast-badge ${status.className}">${status.label}</span>
                </div>
            `;
        })
        .join("");
}

// ─── 추가: 알림 설정된 버튼에 시각적 표시 ─────────────────────

function isAlarmSet(time) {
    return getReservationCount(time) > 0;
}

function markAlarmButton(time) {
    document.querySelectorAll(".time").forEach((btn) => {
        if (btn.textContent.trim() === time) {
            btn.classList.add("alarm-set");
        }
    });
}

function unmarkAlarmButton(time) {
    document.querySelectorAll(".time").forEach((btn) => {
        if (btn.textContent.trim() === time) {
            btn.classList.remove("alarm-set");
        }
    });
}

function restoreAlarmButtons() {
    const counts = getReservationCounts();
    Object.keys(counts).forEach((time) => {
        if (counts[time] > 0) {
            markAlarmButton(time);
        }
    });
}

function removeReservation(time) {
    fetch("/reservations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ time, action: "remove" }),
    })
        .then((res) => res.json())
        .then((data) => {
            reservationCache = data;
            unmarkAlarmButton(time);
            updateForecast();
        })
        .catch(() => {
            alert("서버에 연결할 수 없습니다. people_counter.py가 실행 중인지 확인해주세요.");
        });
}

// ─── 기존 코드 유지 ────────────────────────────────────────────

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

    elements.count.textContent = `${safeCount}`;
    elements.percent.textContent = `${roundedPercent}%`;
    elements.capacityText.textContent = `정원 ${MAX_WAITING_COUNT}명`;
    elements.status.textContent = status.label;
    elements.status.className = `status-pill ${status.className}`;
    elements.bar.style.width = `${Math.min(percent, 100)}%`;
    elements.bar.style.background = status.color;

    // Update donut chart (circumference of r=38 ≈ 238.76)
    if (elements.donutCircle) {
        const circ = 238.76;
        const filled = Math.min(percent / 100, 1) * circ;
        elements.donutCircle.style.strokeDasharray = `${filled} ${circ - filled}`;
        elements.donutCircle.style.stroke = status.color;
    }

    // Update info box
    updateInfoBox(percent);
    updateRecommendation(percent);
}

function updateInfoBox(percent) {
    if (!elements.infoMain || !elements.infoSub) return;
    if (percent >= 100) {
        elements.infoMain.textContent = "셔틀버스가 매우 혼잡합니다.";
        elements.infoSub.textContent  = "탑승이 어려울 수 있습니다.";
        elements.infoMain.style.color = "#DC2626";
    } else if (percent >= 60) {
        elements.infoMain.textContent = "셔틀버스가 혼잡합니다.";
        elements.infoSub.textContent  = "대체 교통편 이용을 권장합니다.";
        elements.infoMain.style.color = "#C2410C";
    } else {
        elements.infoMain.textContent = "현재 셔틀버스는 여유 있습니다.";
        elements.infoSub.textContent  = "쾌적한 탑승이 가능합니다.";
        elements.infoMain.style.color = "#1E40AF";
    }
}

// ─── 추가: 혼잡도에 따른 대체 교통 추천 ────────────────────────
// 여유(<60%)면 안내만, 혼잡(>=60%)/위험(>=100%)이면 추천 카드를 강조해 노출
function updateRecommendation(percent) {
    const section = elements.recommendSection;
    const banner = elements.recommendBanner;
    if (!section || !banner) {
        return;
    }

    section.classList.remove("calm", "warn", "danger");

    if (percent >= 100) {
        section.classList.add("danger");
        banner.textContent = "⚠️ 셔틀버스가 매우 혼잡합니다. 아래 대체 교통편을 강력히 추천합니다!";
    } else if (percent >= 60) {
        section.classList.add("warn");
        banner.textContent = "🚍 셔틀버스가 혼잡합니다. 아래 대체 교통편을 이용해보세요.";
    } else {
        section.classList.add("calm");
        banner.textContent = "🙂 지금은 셔틀버스가 여유롭습니다. 혼잡해지면 대체 교통편을 추천해드려요.";
    }
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

// ─── 주차장 현황 / 스트림 ─────────────────────────────

function getParkingStatus(available, total) {
    if (total <= 0 || available <= 0) {
        return { label: "만차", color: "#002C77", className: "danger" };
    }
    const ratio = available / total;
    if (ratio <= 0.2) {
        return { label: "혼잡", color: "#002C77", className: "warning" };
    }
    return { label: "여유", color: "#00AFEC", className: "" };
}

function updateParkingDashboard(data) {
    const total = Math.max(0, Number(data.total) || 0);
    const parked = Math.max(0, Number(data.parked) || 0);
    const available = Math.max(0, Number(data.available ?? total - parked) || 0);
    const status = getParkingStatus(available, total);
    const usedPercent = total > 0 ? (parked / total) * 100 : 0;

    elements.parkingAvailable.textContent = `${available}`;
    elements.parkingCount.textContent = `${parked}대`;
    elements.parkingCapacity.textContent = `전체 ${total}면`;
    elements.parkingStatus.textContent = status.label;
    elements.parkingStatus.className = status.className;
    elements.parkingBar.style.width = `${Math.min(usedPercent, 100)}%`;
    elements.parkingBar.style.background = status.color;
}

async function loadParkingState() {
    try {
        const response = await fetch(`${PARKING_STATE_URL}?t=${Date.now()}`);
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        updateParkingDashboard(data);
    } catch (error) {
        // parking_counter.py 미실행 시 무시
    }
}

function startParkingStream() {
    elements.parkingMessage.style.display = "block";
    elements.parkingFrame.style.display = "none";
    elements.parkingMessage.textContent = "주차장 영상을 기다리는 중입니다.";
    elements.parkingFrame.src = `${PARKING_STREAM_URL}?t=${Date.now()}`;
}

function stopParkingStream() {
    elements.parkingFrame.removeAttribute("src");
    elements.parkingFrame.style.display = "none";
    elements.parkingMessage.style.display = "block";
}

function showParkingFrame() {
    elements.parkingMessage.style.display = "none";
    elements.parkingFrame.style.display = "block";
}

function showParkingMessage() {
    elements.parkingFrame.style.display = "none";
    elements.parkingMessage.style.display = "block";
    elements.parkingMessage.textContent = "주차장 영상을 불러올 수 없습니다. parking_counter.py가 실행 중인지 확인해주세요.";
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

    if (view === "parking") {
        startParkingStream();
        loadParkingState();
    } else {
        stopParkingStream();
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
    const alreadySet = isAlarmSet(time);

    if (alreadySet) {
        elements.popupText.textContent = `${selectedTime} 버스 알림이 이미 설정되어 있습니다. 취소하시겠습니까?`;
        elements.setAlarmButton.textContent = "알림 취소";
        elements.setAlarmButton.dataset.mode = "cancel";
    } else {
        elements.popupText.textContent = `${selectedTime} 버스 출발 15분 전 알림을 설정하시겠습니까?`;
        elements.setAlarmButton.textContent = "설정";
        elements.setAlarmButton.dataset.mode = "set";
    }

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

    if (elements.setAlarmButton.dataset.mode === "cancel") {
        removeReservation(selectedTime);
        showToastCancel(selectedTime);
        return;
    }

    await addReservation(selectedTime);
    showToastSet(selectedTime);

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
    }
}

function showToastSet(time) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = "toast-item toast-info";
    toast.innerHTML = `
        <div class="toast-icon"><i class="ti ti-bell" aria-hidden="true"></i></div>
        <div class="toast-body">
            <p class="toast-eyebrow">알림 설정 완료</p>
            <p class="toast-title">${time} 버스 알림 설정됨</p>
            <p class="toast-sub">출발 15분 전에 알려드릴게요</p>
        </div>
        <button class="toast-close" aria-label="닫기"><i class="ti ti-x"></i></button>
    `;
    toast.querySelector(".toast-close").addEventListener("click", () => dismissToast(toast));
    container.appendChild(toast);
    setTimeout(() => dismissToast(toast), 4000);
}

function showToastCancel(time) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = "toast-item toast-warning";
    toast.innerHTML = `
        <div class="toast-icon"><i class="ti ti-bell-off" aria-hidden="true"></i></div>
        <div class="toast-body">
            <p class="toast-eyebrow">알림 취소됨</p>
            <p class="toast-title">${time} 버스 알림 취소됨</p>
            <p class="toast-sub">해당 시간 알림이 해제되었습니다</p>
        </div>
        <button class="toast-close" aria-label="닫기"><i class="ti ti-x"></i></button>
    `;
    toast.querySelector(".toast-close").addEventListener("click", () => dismissToast(toast));
    container.appendChild(toast);
    setTimeout(() => dismissToast(toast), 4000);
}

function getToastLevel(time) {
    const count = getReservationCount(time);
    const percent = (count / MAX_WAITING_COUNT) * 100;
    if (percent >= 100) return { level: "danger", label: "위험 · 정원 초과 예상" };
    if (percent >= 60) return { level: "warning", label: `혼잡 예정 · 예약 ${count}명` };
    return { level: "info", label: `예약 ${count}명` };
}

function showToast(time) {
    const container = document.getElementById("toast-container");
    const { level, label } = getToastLevel(time);
    const count = getReservationCount(time);
    const percent = Math.min((count / MAX_WAITING_COUNT) * 100, 100);

    const toast = document.createElement("div");
    toast.className = `toast-item toast-${level}`;
    toast.innerHTML = `
        <div class="toast-icon"><i class="ti ti-bus" aria-hidden="true"></i></div>
        <div class="toast-body">
            <p class="toast-eyebrow">Departure Alert</p>
            <p class="toast-title">${time} 버스 출발 15분 전</p>
            <p class="toast-sub">${label}</p>
            <div class="toast-progress">
                <div class="toast-progress-fill" style="width:${percent}%"></div>
            </div>
        </div>
        <button class="toast-close" aria-label="닫기"><i class="ti ti-x"></i></button>
    `;

    toast.querySelector(".toast-close").addEventListener("click", () => dismissToast(toast));
    container.appendChild(toast);
    setTimeout(() => dismissToast(toast), 6000);
}

function dismissToast(toast) {
    if (!toast.parentNode) return;
    toast.classList.add("toast-out");
    toast.addEventListener("animationend", () => toast.remove(), { once: true });
}

function showNotification(time) {
    showToast(time);

    if ("Notification" in window && Notification.permission === "granted") {
        new Notification("셔틀버스 알림", {
            body: `${time} 버스 출발 15분 전입니다.`,
        });
    }
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
    elements.parkingFrame.addEventListener("load", showParkingFrame);
    elements.parkingFrame.addEventListener("error", showParkingMessage);
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

// ─── 실시간 시계 ──────────────────────────────
const DAY_KO = ["일","월","화","수","목","금","토"];

function updateClock() {
    const now = new Date();
    const hh  = String(now.getHours()).padStart(2, "0");
    const mm  = String(now.getMinutes()).padStart(2, "0");
    const ss  = String(now.getSeconds()).padStart(2, "0");
    const yyyy = now.getFullYear();
    const mo   = String(now.getMonth() + 1).padStart(2, "0");
    const dd   = String(now.getDate()).padStart(2, "0");
    const day  = DAY_KO[now.getDay()];

    if (elements.clock)       elements.clock.textContent       = `${hh}:${mm}:${ss}`;
    if (elements.dateDisplay) elements.dateDisplay.textContent = `${yyyy}.${mo}.${dd} (${day})`;
}

bindEvents();
updateDashboard(DEFAULT_WAITING_COUNT);
loadCountState();
fetchReservations();
updateClock();
window.setInterval(loadCountState,   1000);
window.setInterval(fetchReservations, 3000);
window.setInterval(loadParkingState, 1000);
window.setInterval(updateClock,      1000);