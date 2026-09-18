#include "pch.h"
#include "utility_class.h"
#include <sstream>
#include <iomanip>

system_clock::time_point utility_class::parse_time_string(const string& time_str) {
  std::tm tm = {};
  istringstream ss(time_str);
  ss >> get_time(&tm, "%Y-%m-%d %H:%M:%S");
  auto tp = system_clock::from_time_t(std::mktime(&tm));
  return tp;
}

string utility_class::get_accelerator_name(accelator_type type) {
  switch (type) {
  case accelator_type::any:
    return "any";
  case accelator_type::cpu:
    return "CPU";
  case accelator_type::v100:
    return "V100";
  case accelator_type::a100:
    return "A100";
  case accelator_type::a30:
    return "A30";
  case accelator_type::h100:
    return "H100";
  case accelator_type::l4:
    return "L4";
  case accelator_type::l40:
    return "L40";
  case accelator_type::b200:
    return "B200";
  default:
    return "CPU";
  }
}

string utility_class::get_elapsed_time(system_clock::time_point tp) {
  chrono::duration<double> elapsed_seconds = system_clock::now() - tp;
  auto elapsed_duration = chrono::duration_cast<std::chrono::seconds>(elapsed_seconds);
  string elapsed_time = utility_class::format_duration(elapsed_duration);
  return elapsed_time;
}

string utility_class::format_duration(chrono::seconds duration) {
  int hours = chrono::duration_cast<chrono::hours>(duration).count();
  int minutes = chrono::duration_cast<chrono::minutes>(duration).count() % 60;
  int seconds = duration.count() % 60;

  stringstream ss;
  ss << setw(2) << setfill('0') << hours << ":"
    << setw(2) << setfill('0') << minutes << ":"
    << setw(2) << setfill('0') << seconds;
  return ss.str();
}

string utility_class::conver_tp_str(const system_clock::time_point tp){

 /* string time_string = format("{:%Y-%m-%d %H:%M:%S}", tp);
  return time_string;*/

  time_t time = system_clock::to_time_t(tp);
  tm local_tm;
#ifdef _WIN32
  localtime_s(&local_tm, &time); // Windows의 경우
#else
  localtime_r(&time, &local_tm); // POSIX 시스템의 경우
#endif

  stringstream ss;
  ss << put_time(&local_tm, "%Y-%m-%d %H:%M:%S") << "+00:00";

  return ss.str();
}

string utility_class::double_to_string(double value){
  std::ostringstream oss;
  oss << std::fixed << std::setprecision(0) << value;
  return oss.str();
}

system_clock::time_point utility_class::get_time_after(system_clock::time_point start, int min) {
  return start + std::chrono::minutes(min);
}

system_clock::time_point utility_class::get_time_after(const string& time_str, int min) {
  return get_time_after(parse_time_string(time_str), min);
}
