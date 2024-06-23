"""
코드 실행 전 Cloud Speech API 사용 준비가 필요함
1. Google API키 발급
2. 환경변수 설정
3. Cloud SDK 설치
4. 터미널로 하단 부분 설치 및 설정
pip install pyaudio
pip install --upgrade google-cloud-storage
pip install google-cloud-speech
gcloud auth activate-service-account --key-file="json 키 경로"
"""

import re # 정규 표현식을 지원하는 모듈
import sys # 파이썬 인터프리터와 관련된 변수와 함수를 제공하는 모듈

from google.cloud import speech #구글 STT 라이브러리 가져오기
import pyaudio # 오디오 스트림 처리 라이브러리
from six.moves import queue # 호환성 유지 모듈, 오디오 데이터 버퍼를 위해 사용

# 오디오 레코딩 파라미터 설정
RATE = 16000 #샘플링 주파수 16000Hz,  초당 샘플링되는 데이터 포인트의 수
CHUNK = int(RATE / 10)  # 청크 크기 100, 오디오 스트림을 작은 조각으로 나누는 것

# 오디오 녹음 스트림을 열고, 오디오 청크를 생성하며 반환함.
class MicrophoneStream(object):
    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk

        self._buff = queue.Queue()
        self.closed = True

        # 오디오 스트림 시작 역할
    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        # PyAudio 객체 생성
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            # 오디오 인터페이스는 현재 단일 채널 오디오만 지원
            # https://goo.gl/z757pE
            channels=1, rate=self._rate,
            input=True, frames_per_buffer=self._chunk,

            # 오디오 스트림을 비동기적으로 실행하여 버퍼를 채움
            # 호출 중인 스레드가 네트워크 요청 등 다른 작업을 하는 동안 입력 장치의 버퍼가 오버플로우되지 않도록 하기 위해 필요함
            stream_callback=self._fill_buffer,
        )

        self.closed = False
        # 스트림이 열려 있음

        print('Start')

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
        # pyaudio.paContinue를 반환하여 오디오 스트림에서 추가적인 데이터를 계속 수집

    # 오디오 스트림에서 데이터를 가져와서 처리할 수 있도록 청크 단위로 반환
    def generator(self):
        while not self.closed:
            chunk = self._buff.get()
            # 버퍼에서 데이터 청크 가져오기

            if chunk is None:
                return
            # 오디오 스트림이 종료되었으면 반환
            data = [chunk]
            # 가져온 청크를 리스트에 저장

            # 나머지 데이터 가져오기
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                    # 가져온 청크를 데이터 리스트에 추가
                except queue.Empty:
                    break
                # 버퍼 데이터가 없으면 break

            yield b''.join(data)

# API의 서버 응답을 반복하여 출력
def listen_print_loop(responses):
    num_chars_printed = 0

    # 서버 응답을 반복하여 처리
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

        else:
            print(transcript + overwrite_chars)

            if re.search(r'\b(끝|그만)\b', transcript, re.I):
                print('Exiting..')
                break

            num_chars_printed = 0
            # 최종 결과(전체 음성 인식 결과)인 경우, 결과를 출력하고 프로그램이 종료되어야 할 키워드인지 확인 후 종료

def main():
    language_code = 'ko-KR'
    # 인식 음성 언어 코드 설정

    client = speech.SpeechClient()
    # 오디오 데이터->서버=>텍스트 변환

    # API 호출에 필요한 설정 정보
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=language_code)
    # 인코딩 방식: LINEAR16, 오디오 데이터 샘플링 주파수
    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=True)
    # 실시간 음성 처리 설정

    # Audio Stream 생성
    with MicrophoneStream(RATE, CHUNK) as stream:
        audio_generator = stream.generator()
        # MicrophoneStream Class 오디오 생성 제너레이터 가져오기
        requests = (speech.StreamingRecognizeRequest(audio_content=content)
                    for content in audio_generator)
        # 오디오 데이터 StreamingRecognizeRequest 객체로 변환하여 요청을 생성
        responses = client.streaming_recognize(streaming_config, requests)
        #
        # 생성된 요청을 사용하여 구글 STT에 스트리밍 인식 요청을 실행
        listen_print_loop(responses)
        # 서버 응답을 반복하여 출력하는 함수를 호출하여 결과 호출


if __name__ == '__main__':
    main()
# [END speech_transcribe_streaming_mic]
