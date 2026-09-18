
// gpu_scheduer.h : main header file for the gpu_scheduer application
//
#pragma once

#ifndef __AFXWIN_H__
	#error "include 'pch.h' before including this file for PCH"
#endif

#include "resource.h"       // main symbols


// CgpuscheduerApp:
// See gpu_scheduer.cpp for the implementation of this class
//

class CgpuscheduerApp : public CWinApp
{
public:
	CgpuscheduerApp() noexcept;


// Overrides
public:
	virtual BOOL InitInstance();
	virtual int ExitInstance();

// Implementation
	afx_msg void OnAppAbout();
	DECLARE_MESSAGE_MAP()
};

extern CgpuscheduerApp theApp;
