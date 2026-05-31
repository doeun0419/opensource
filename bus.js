const monitorStreamUrl = "/video_feed";

function showCamera() {
    document.getElementById("main-page").style.display = "none";
    document.getElementById("camera-page").style.display = "block";

    const frame = document.getElementById("monitor-frame");
    const message = document.getElementById("monitor-message");

    if (message) {
        message.style.display = "block";
        message.innerText = "people_counter.py 실행 화면을 기다리는 중입니다.";
    }
    if (frame) {
        frame.style.display = "block";
        if (message) {
            message.style.display = "none";
        }
        frame.src = monitorStreamUrl + "?t=" + Date.now();
    }
}

function showMain() {
    document.getElementById("camera-page").style.display = "none";
    document.getElementById("main-page").style.display = "block";
}

function showMonitorMessage() {
    const frame = document.getElementById("monitor-frame");
    const message = document.getElementById("monitor-message");

    if (!frame || !message) {
        return;
    }

    frame.style.display = "none";
    message.style.display = "block";
    message.innerText = "people_counter.py를 실행하면 여기에 화면이 표시됩니다.";
}

const max = 50;
const countStateUrl = "utils/data/count_state.json";

function updateDashboard(count) {
    let safeCount = Math.max(0, Number(count) || 0);
    let percent = (safeCount / max) * 100;
    let bar = document.getElementById("bar");
    let status = "여유";
    let color = "green";

    if (percent >= 60) {
        status = "혼잡";
        color = "orange";
    }
    if (percent >= 100) {
        status = "위험";
        color = "red";
    }

    document.getElementById("count").innerText = safeCount + "명";
    document.getElementById("percent").innerText = percent.toFixed(1) + "%";
    document.getElementById("status").innerText = status;
    bar.style.width = Math.min(percent, 100) + "%";
    bar.style.background = color;
}

async function loadCountState() {
    try {
        const response = await fetch(countStateUrl + "?t=" + Date.now());
        if (!response.ok) {
            return;
        }

        const data = await response.json();
        updateDashboard(data.current_inside);
    } catch (error) {
        updateDashboard(0);
    }
}

updateDashboard(0);
loadCountState();
setInterval(loadCountState, 1000);

// 알림 권한 요청
function requestPermission() {
    if (Notification.permission !== "granted") {
        Notification.requestPermission();
    }
}

// 페이지 처음 로드 시 실행
requestPermission();

let selectedTime = "";

// 시간 클릭 이벤트
document.querySelectorAll(".time").forEach(el => {
    el.addEventListener("click", () => {
        selectedTime = el.innerText;
        document.getElementById("popup-text").innerText =
            selectedTime + " 버스\n15분 전 알림을 설정하시겠습니까?";
        document.getElementById("popup").style.display = "flex";
    });
});

function closePopup() {
    document.getElementById("popup").style.display = "none";
}

// 🔥 진짜 알림 설정
function setAlarm() {
    closePopup();

    let now = new Date();

    // 선택한 시간 파싱
    let [hour, minute] = selectedTime.split(":").map(Number);

    let target = new Date();
    target.setHours(hour);
    target.setMinutes(minute - 15); // 15분 전
    target.setSeconds(0);

    // 이미 지난 시간이면 다음 날로
    if (target < now) {
        target.setDate(target.getDate() + 1);
    }

    let delay = target - now;

    alert("알림이 설정되었습니다!");

    setTimeout(() => {
        showNotification(selectedTime);
    }, delay);
}

// 🔔 알림 표시
function showNotification(time) {
    if (Notification.permission === "granted") {
        new Notification("셔틀버스 알림", {
            body: time + " 버스 15분 전입니다!",
        });
    } else {
        alert(time + " 버스 15분 전입니다!");
    }
}
