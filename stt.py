import pyaudio
import pandas as pd
import re # 정규 표현식을 지원하는 모듈
import sys # 파이썬 인터프리터와 관련된 변수와 함수를 제공하는 모듈
import os

from six.moves import queue
from google.cloud import speech

RATE = 16000
CHUNK = int(RATE / 10)  # 100ms

# 오디오 녹음 스트림을 열고, 오디오 청크를 생성하며 반환함.
class MicrophoneStream(object):
    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk

        self._buff = queue.Queue()
        self.closed = True

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        # PyAudio 객체 생성
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1, rate=self._rate,
            input=True, frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )

        self.closed = False
        print('Starting..')
        return self

    # 오디오 스트림을 닫고 자원 정리
    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        self._buff.put(None)
        self._audio_interface.terminate()

    # 오디오 데이터를 지속적으로 수집하여 버퍼에 입력
    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        self._buff.put(in_data)

        return None, pyaudio.paContinue

    # 오디오 스트림에서 데이터를 가져와서 처리할 수 있도록 청크 단위로 반환
    def generator(self):
        while not self.closed:
            chunk = self._buff.get()

            if chunk is None:
                return
            data = [chunk]

            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break
            yield b''.join(data)

# API의 서버 응답을 반복하여 출력
def listen_print_loop(responses):
    num_chars_printed = 0

    for response in responses:
        # 결과가 없는 경우 건너뛰기
        if not response.results:
            continue
        result = response.results[0]
        # 첫 번째 결과만 고려

        # 현재 결과에 대한 대안이 없는지 확인
        if not result.alternatives:
            continue

        transcript = result.alternatives[0].transcript
        # 최상위 대안만 가져오기
        overwrite_chars = ' ' * (num_chars_printed - len(transcript))
        # 중간 결과를 출력할 때 이전에 출력된 문자 수가 현재 결과의 길이보다 길다면, 이전 결과를 덮어쓰기 위해 추가적인 공백 문자열을 생성

        # 현재 결과가 최종 결과인지 확인
        if not result.is_final:
            sys.stdout.write(transcript + overwrite_chars + '\r')
            sys.stdout.flush()
            num_chars_printed = len(transcript)
            # 현재까지 출력된 문자 수를 저장(덮어쓰기)

        # 데이터 프레임 생성하여 CSV 파일 저장
        else:
            words = transcript.split() # 띄어쓰기로 구분하여 단어 저장
            df = pd.DataFrame([words])

            if not os.path.exists("C:/Temp/result/stt_result.csv"):
                df.to_csv("C:/Temp/result/stt_result.csv", index = False, mode = 'w', encoding= 'utf-8-sig')
            # 누적 저장
            else:
                df.to_csv("C:/Temp/result/stt_result.csv", index = False, mode= 'a', encoding= 'utf-8-sig', header = False)
            #출력 결과 미리 보기
            print(df)

            if re.search(r'\b(그려 줘)\b', transcript, re.I): #'그려 줘'를 인식하면 자동으로 종료
                print('Exiting..')
                break

            num_chars_printed = 0
            # 최종 결과(전체 음성 인식 결과)인 경우, 결과를 출력하고 프로그램이 종료되어야 할 키워드인지 확인 후 종료


def main():
    language_code = 'ko-KR'

    client = speech.SpeechClient()

    # API 호출에 필요한 설정 정보
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=language_code)
    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=True)

    with MicrophoneStream(RATE, CHUNK) as stream:
        audio_generator = stream.generator()
        requests = (speech.StreamingRecognizeRequest(audio_content=content)
                    for content in audio_generator)

        # 생성된 요청을 사용하여 구글 STT에 스트리밍 인식 요청을 실행
        responses = client.streaming_recognize(streaming_config, requests)
        listen_print_loop(responses)

if __name__ == '__main__':
    main()
