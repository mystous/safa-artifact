#pragma once
#include "afxdialogex.h"

#include "server_entry.h"
#include <vector>

// CGPUStatus 대화 상자

class CGPUStatus : public CDialog
{
	DECLARE_DYNAMIC(CGPUStatus)

public:
	CGPUStatus(CWnd* pParent = nullptr);   // 표준 생성자입니다.
	virtual ~CGPUStatus();
  void set_server_list(std::vector<server_entry>* list) { server_list = list; };

// 대화 상자 데이터입니다.
#ifdef AFX_DESIGN_TIME
	enum { IDD = IDD_DIALOG_GPU_LIST};
#endif


protected:
	virtual void DoDataExchange(CDataExchange* pDX);    // DDX/DDV 지원입니다.

	DECLARE_MESSAGE_MAP()
public:
  virtual BOOL OnInitDialog();
private:
  std::vector<server_entry>* server_list = nullptr;
  CListCtrl server_list_ctrl;
};
