#pragma once
#include "afxdialogex.h"
#include "enum_definition.h"
#include <vector>


// log_gen_dialog 대화 상자

class log_gen_dialog : public CDialogEx
{
	DECLARE_DYNAMIC(log_gen_dialog)

public:
	log_gen_dialog(CWnd* pParent = nullptr);   // 표준 생성자입니다.
	virtual ~log_gen_dialog();

// 대화 상자 데이터입니다.
#ifdef AFX_DESIGN_TIME
	enum { IDD = IDD_DIALOG_log_gen };
#endif

protected:
	virtual void DoDataExchange(CDataExchange* pDX);    // DDX/DDV 지원입니다.

	DECLARE_MESSAGE_MAP()
public:
  CString task_count_string;
  BOOL run_after_gen;
  bool all_random_dist = false;
  afx_msg void OnBnClickedCheckRamdom();
  CButton all_random_check;
private:
  void change_option_diable(bool disable);
  void GetSelectedCheckboxes(std::vector<distribution_type>& selected_dist);
public:
  virtual BOOL OnInitDialog();
  CListBox parameter_dist_list;
  std::vector<distribution_type> selected_parameter_distribution;
  afx_msg void OnLvnItemchangedListCtlParamDist(NMHDR* pNMHDR, LRESULT* pResult);
  afx_msg void OnNMCustomDrawListCtrl(NMHDR* pNMHDR, LRESULT* pResult);
  CListCtrl param_distribution_list;
  afx_msg void OnClickListCtlParamDist(NMHDR* pNMHDR, LRESULT* pResult);
  afx_msg void OnBnClickedOk();
};
