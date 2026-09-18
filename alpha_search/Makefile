# 컴파일러 설정
CC = g++
CXXFLAGS = -Wall -Wextra -std=c++20

# 헤더 파일 목록
HEADERS = \
    src/enum_definition.h \
    src/global_definistion.h \
    src/job_emulator.h \
    src/scheduler_fare_share.h \
    src/server_entry.h \
    src/call_back_object.h \
    src/job_entry.h \
    src/scheduler_mostallocated.h \
    src/coprocessor_server.h \
    src/job_scheduler.h \
    src/scheduler_compact.h \
    src/utility_class.h \
    src/call_back_object.h \
    src/scheduler_mcts.h \
    src/utility_class.h \
    src/experiment_perform.h \
    src/adjusting_server.h \
    src/scheduler_round_robin.h

# 소스 파일 목록
SOURCES = \
    src/job_scheduler.cpp \
    src/scheduler_fare_share.cpp \
    src/server_entry.cpp \
    src/call_back_object.cpp \
    src/job_emulator.cpp \
    src/scheduler_mostallocated.cpp \
    src/coprocessor_server.cpp \
    src/job_entry.cpp \
    src/scheduler_compact.cpp \
    src/scheduler_mcts.cpp \
    src/utility_class.cpp \
    src/utility_class.cpp \
    src/experiment_perform.cpp \
    src/adjusting_server.cpp \
    src/scheduler_round_robin.cpp \
    src/linux_main.cpp

# 오브젝트 파일 목록
OBJECTS = $(SOURCES:.cpp=.o)

# 실행 파일 이름
TARGET = experiment_gpu

# 기본 목표
all: $(TARGET)

# 실행 파일 생성 규칙
$(TARGET): $(OBJECTS)
	$(CC) $(CXXFLAGS) -o $@ $^

# 오브젝트 파일 생성 규칙
%.o: %.cpp $(HEADERS)
	$(CC) $(CXXFLAGS) -c $< -o $@

# 깨끗하게 만들기 규칙
clean:
	rm -f $(OBJECTS) $(TARGET)

# 재빌드 규칙
rebuild: clean all
