function showCamera() {
    document.getElementById("main-page").style.display = "none";
    document.getElementById("camera-page").style.display = "block";
}

function showMain() {
    document.getElementById("camera-page").style.display = "none";
    document.getElementById("main-page").style.display = "block";
}

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

