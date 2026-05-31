# Shuttle Waiting Dashboard

This project is a school project based on the open-source
`People-Counting-in-Real-Time` repository. It adapts real-time people counting
for a campus shuttle waiting dashboard.

The goal is to show shuttle waiting status in a simple web UI:

- real-time waiting count
- crowd level based on shuttle capacity
- shuttle timetable
- departure reminder popup
- camera/monitoring screen

## Original Project

Based on the open-source `People-Counting-in-Real-Time` project and the
PyImageSearch people counter tutorial:
https://www.pyimagesearch.com/2018/08/13/opencv-people-counter/

## Project Files

- `people_counter.py`: people counting and local web server
- `bus.html`: shuttle dashboard page
- `bus.css`: dashboard styling
- `bus.js`: dashboard interaction and count polling
- `utils/data/count_state.json`: latest waiting count state
- `detector/`: MobileNet SSD model files
- `tracker/`: centroid tracking logic

## Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Run with a test video:

```bash
python people_counter.py \
  --prototxt detector/MobileNetSSD_deploy.prototxt \
  --model detector/MobileNetSSD_deploy.caffemodel \
  --input utils/data/tests/test_1.mp4
```

Run with webcam or camera settings from `utils/config.json`:

```bash
python people_counter.py \
  --prototxt detector/MobileNetSSD_deploy.prototxt \
  --model detector/MobileNetSSD_deploy.caffemodel
```

## Notes

This is made for a campus shuttle waiting-system prototype. The current
reservation count in the reminder popup is stored in browser `localStorage`,
so it is for frontend/demo use and is not shared between users.

## License

This project is released under the MIT License. See `LICENSE`.
