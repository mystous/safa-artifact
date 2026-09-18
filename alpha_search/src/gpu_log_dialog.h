#pragma once
#include "afxdialogex.h"

#include "job_entry.h"
#include <vector>

// gpu_log_dialog 대화 상자

class gpu_log_dialog : public CDialog
{
	DECLARE_DYNAMIC(gpu_log_dialog)

public:
	gpu_log_dialog(CWnd* pParent = nullptr);   // 표준 생성자입니다.
	virtual ~gpu_log_dialog();

// 대화 상자 데이터입니다.
#ifdef AFX_DESIGN_TIME
	enum { IDD = IDD_gpu_log_dialog };
#endif

protected:
	virtual void DoDataExchange(CDataExchange* pDX);    // DDX/DDV 지원입니다.

	DECLARE_MESSAGE_MAP()
public:
  void set_job_list(std::vector<job_entry>* job_entry_list) { job_list = job_entry_list; };
  virtual INT_PTR DoModal();
private:
  std::vector<job_entry> *job_list = nullptr;
  CListCtrl job_list_ctrl;
public:
  virtual BOOL OnInitDialog();
};
